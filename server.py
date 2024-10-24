
import aiohttp
import os
import argparse
import subprocess
import sys
import uvicorn

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pydantic import BaseModel
from dotenv import load_dotenv  # Import dotenv to load .env file

# Define a Pydantic model to parse the incoming JSON body
class StartAgentRequest(BaseModel):
    url: str
    token: str

MAX_BOTS_PER_ROOM = 1

# Bot sub-process dict for status reporting and concurrency control
bot_procs = {}
daily_helpers = {}

load_dotenv()

bots   = [ "silent_bot", "echo_bot" , "echo_bot" , "echo_bot" , "echo_bot" , "echo_bot", "echo_bot" , "echo_bot" ]
props  = [ "0"         , "0"        , "250"      , "500"      , "750"      , "1000"    , "1500"     , "2000"     ]
paths  = [ f"{bot}_{prop}" for bot,prop in zip(bots,props) ]


async def register_bot(aiohttp_session, config, available: bool):

    server = os.getenv("BIRDCONV_SERVER")
    birdconv_url = f"{server}/api/register"

    payload = { "bots": {} }
    
    for bot,path  in zip(bots,paths) :
        payload["bots"][ f"{path}"] = {
            "uid"      : os.getenv("API_KEY"),
            "service"  : f"{APP_HOST}/{path}",
            "available": available
        }

    try:
        async with aiohttp_session.post(birdconv_url, json=payload) as response:
            if response.status != 200:
                print(f"Failed to register bot: {response.status}")
            else:
                print(f"Bot {'registered' if available else 'unregistered'} successfully.")
    except Exception as e:
        print(f"Error registering bot: {e}")

def cleanup():
    for entry in bot_procs.values():
        proc = entry[0]
        proc.terminate()
        proc.wait()


def configure() :
    host = "0.0.0.0"
    port = int(os.getenv("FAST_API_PORT", "7860"))
    parser = argparse.ArgumentParser(description="Birdconv FastAPI server")
    parser.add_argument("--host", type=str,default=host, help="Host address")
    parser.add_argument("--port", type=int,default=port, help="Port number")
    parser.add_argument("--reload", action="store_true",help="Reload code on change")
    return parser.parse_args()


@asynccontextmanager
async def lifespan(app: FastAPI):

    config = configure()

    print(f"Starting FastAPI server on {config.host}:{config.port}")

    aiohttp_session = aiohttp.ClientSession()
    await register_bot(aiohttp_session,config, available=True)

    yield

    # await register_bot(aiohttp_session,config, available=False)
    await aiohttp_session.close()
    cleanup()

APP_HOST        = os.getenv("APP_HOST","http://0.0.0.0")
RUN_AS_PROCESS  = os.getenv("RUN_AS_PROCESS", "true").lower() == "true"
FLY_API_HOST    = os.getenv("FLY_API_HOST", "https://api.machines.dev/v1")
FLY_APP_NAME    = os.getenv("FLY_APP_NAME", "docker-bot")
FLY_API_TOKEN   = os.getenv("FLY_API_TOKEN", "")
FLY_HEADERS     = {
    'Authorization': f"Bearer {FLY_API_TOKEN}",
    'Content-Type': 'application/json'
}

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def spawn_fly_machine(bot_name: str, url: str, token: str, delay:str):
    async with aiohttp.ClientSession() as session:
        # Use the same image as the bot runner
        async with session.get(f"{FLY_API_HOST}/apps/{FLY_APP_NAME}/machines", headers=FLY_HEADERS) as r:
            if r.status != 200:
                text = await r.text()
                raise Exception(f"Unable to get machine info from Fly: {text}")

            data = await r.json()
            image = data[0]['config']['image']

        # Machine configuration
        cmd = f"python3  -m {bot_name} -u {url} -t {token} -d {delay}"
        cmd = cmd.split()
        worker_props = {
            "config": {
                "image": image,
                "auto_destroy": True,
                "init": {
                    "cmd": cmd
                },
                "restart": {
                    "policy": "no"
                },
                "guest": {
                    "cpu_kind": "shared",
                    "cpus": 1,
                    "memory_mb": 1024
                }
            },
        }

        # Spawn a new machine instance
        async with session.post(f"{FLY_API_HOST}/apps/{FLY_APP_NAME}/machines", headers=FLY_HEADERS, json=worker_props) as r:
            if r.status != 200:
                text = await r.text()
                raise Exception(f"Problem starting a bot worker: {text}")

            data = await r.json()
            # Wait for the machine to enter the started state
            vm_id = data['id']

        async with session.get(f"{FLY_API_HOST}/apps/{FLY_APP_NAME}/machines/{vm_id}/wait?state=started", headers=FLY_HEADERS) as r:
            if r.status != 200:
                text = await r.text()
                raise Exception(f"Bot was unable to enter started state: {text}")

    print(f"Machine joined room: {url}")



async def check_and_run( bot_name , url, token, delay):

    if not bot_name:
        raise HTTPException(status_code=500,detail="Missing 'bot_name' property in request data. Cannot start agent")

    if not url :
        raise HTTPException(status_code=500,detail="Missing 'url' property in request data. Cannot start agent")
    
    if not token:
        raise HTTPException(status_code=500,detail="Missing 'token' property in request data. Cannot start agent")

    if RUN_AS_PROCESS :

        num_bots_in_room = sum(1 for proc in bot_procs.values() if proc[1] == url and proc[0].poll() is None)
        if num_bots_in_room >= MAX_BOTS_PER_ROOM:
            return JSONResponse({"message": f"Agent already started for room {url}", "bot_pid": proc.pid})
        try:
            proc = subprocess.Popen([f"python3 -m {bot_name} -u {url} -t {token} -d {delay}"],shell=True,bufsize=1,stderr=subprocess.STDOUT,  cwd=os.path.dirname(os.path.abspath(__file__) ), text=True   )
            bot_procs[proc.pid] = (proc, url)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start subprocess: {e}")
    else:
        try:
            await spawn_fly_machine(bot_name, url, token, delay)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to spawn VM: {e}")
    
    return JSONResponse({"message": f"{bot_name} started for room {url}"})


@app.get(f"/")
def test( request ) :
    return JSONResponse({"message": f"{FLY_APP_NAME} started for url {APP_HOST}"})

@app.post(f"/{paths[0]}")
async def start_agent(request: StartAgentRequest):
    await check_and_run(bots[0], request.url, request.token, props[0] )

@app.post(f"/{paths[1]}")
async def start_agent(request: StartAgentRequest):
    await check_and_run(bots[1], request.url, request.token, props[1] )

@app.post(f"/{paths[2]}")
async def start_agent(request: StartAgentRequest):
    await check_and_run(bots[2], request.url, request.token, props[2] )

@app.post(f"/{paths[3]}")
async def start_agent(request: StartAgentRequest):
    await check_and_run(bots[3], request.url, request.token, props[3] )

@app.post(f"/{paths[4]}")
async def start_agent(request: StartAgentRequest):
    await check_and_run(bots[4], request.url, request.token, props[4] )

@app.post(f"/{paths[5]}")
async def start_agent(request: StartAgentRequest):
    await check_and_run(bots[5], request.url, request.token, props[5] )

@app.post(f"/{paths[6]}")
async def start_agent(request: StartAgentRequest):
    await check_and_run(bots[6], request.url, request.token, props[6] )

@app.post(f"/{paths[7]}")
async def start_agent(request: StartAgentRequest):
    await check_and_run(bots[7], request.url, request.token, props[7] )

if __name__ == "__main__":

    config = configure()

    uvicorn.run(
        "server:app",
        host=config.host,
        port=config.port,
        reload=config.reload
    )