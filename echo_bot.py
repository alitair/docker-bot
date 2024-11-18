import time
import threading
import json
from typing import Mapping
from   daily import *
from   runner import configure
import cv2
from PIL import Image
import struct
import numpy as np
import queue
import gc


ASSUMED_LATENCY = 0.150

class MediaBuffer : 

    def __init__(self, max_delay,maxsize=1) :
        self.buffer       = []
        self._delay       = 0.0
        self.read_index   = -1
        self.max_delay    = max_delay
        self.frame_queue = queue.Queue(maxsize=maxsize)
        # self.lastTime     = time.time()

    def pop(self) :

        dt = self.buffer[-1].elapsed_time - self.buffer[0].elapsed_time

        if dt  >= self._delay :

            actual_delay = self.buffer[-1].elapsed_time - self.buffer[ self.read_index ].elapsed_time 

            if ( abs( actual_delay - self._delay) > 0.25 ) :
                self.read_index = self._find_index()

            if (dt > self.max_delay + 1.0) :
                self.buffer.pop(0)

            return self.buffer[ self.read_index ]
        else :
            return self.buffer[-1]
    
    
    def _find_index(self) :

        if ( self._delay <= 0.0 ) :
            return -1
            
        index = self.read_index
        
        while ( abs(index) < len(self.buffer) and index < 0) :
            dt_p = (self.buffer[-1].elapsed_time - self.buffer[index    ].elapsed_time) - self._delay 
            dt_m = (self.buffer[-1].elapsed_time - self.buffer[index - 1].elapsed_time) - self._delay
            if ( dt_p * dt_m < 0.0 ) :
                if ( abs(dt_p) < abs(dt_m) ) :
                    return index
                else :
                    return index - 1
            if   ( dt_p < 0.0  and dt_m < 0.0 ) :
                index -= 1
            elif ( dt_p > 0.0 and dt_m > 0.0 ) :
                index += 1
            elif ( dt_p == 0.0 ) :
                return index
            else :   # dt_m == 0.0
                return index - 1

        return index

    def delay(self, value):
        self._delay = max(0, value - ASSUMED_LATENCY ) # 150ms latency

    def addToQueue(self) :
        try:
            self.frame_queue.put( self.pop(), block=False )
        except queue.Full:
            pass

    def getFromQueue(self) :
        try :
            # lastTime = self.lastTime
            data = self.frame_queue.get(block=False)
            # self.lastTime = time.time()
            # if ( self.lastTime - lastTime > 1.0) :
            #     timing = time.time() - data.elapsed_time    
            #     print(f"{self.__class__.__name__} delay is {timing:.2f} seconds. {self.read_index} {len(self.buffer)} {(self.lastTime - lastTime):.2f} {(1.0/(self.lastTime - lastTime)):.2f}")
            return data
        except queue.Empty:
            return None
        
class AudioBuffer(MediaBuffer) :

    def __init__(self, max_delay=5.0,maxsize=1) :
        super().__init__(max_delay,maxsize=maxsize)

    def append(self, data ) :
        self.buffer.append( BufferedAudioData( data , silent = (self._delay <= 0.0) ))
        self.addToQueue()

class VideoBuffer(MediaBuffer) : 

    def __init__(self, camera, max_delay=5.0,maxsize=1) :
        super().__init__(max_delay,maxsize=maxsize)
        self._camera = camera

    def append(self, data ) :
        self.buffer.append( BufferedVideoData( data, self._camera.width, self._camera.height ) )
        self.addToQueue()

class BufferedAudioData :
    def __init__(self, data, silent=False) :
        self.data             = data
        self.elapsed_time     = time.time()
        self.silent           = silent

    def frames(self, silent=False) :
        if self.silent or silent :
            return bytes([0] * int(self.data.num_audio_frames * self.data.num_channels * self.data.bits_per_sample / 8) )
        else :  
            return self.data.audio_frames
        

class BufferedVideoData :
    def __init__(self, data, expected_width, expected_height) :
        self.data            = data
        self.elapsed_time    = time.time() #data.timestamp_us/1000000.0
        self.expected_width  = expected_height
        self.expected_height = expected_width

    def frames(self, silent=False) :
        image = Image.frombytes(self.data.color_format, (self.data.width, self.data.height), self.data.buffer)
        if image.width != self.expected_width or image.height != self.expected_height:
            image = image.resize((self.expected_width, self.expected_height), Image.LANCZOS)  # LANCZOS for high-quality resizing
        return image.transpose(Image.ROTATE_270).tobytes()


class EchoBot(EventHandler):

    def on_call_state_updated(self,state):
        print(f"Call state updated {state}")
        if state == "left":
            self._app_quit = True

    def on_error(self, message):
        print(f"Error: {message}")
        self._app_quit = True

    def on_joined(self, data, error):
        if error :
            print(f"on_joined error {error}")
            self._app_quit = True
        else :
            print("on_joined successful")

        if error:
            print(f"Unable to join meeting: {error}")
            self._app_quit = True

        self.subscribe( self._find_bird( data["participants"]) )
        self.send_ui()

    def on_participant_joined(self, participant):
        print(f"on_participant_joined " + participant["id"] )

        if (self._is_bird(participant)) :
            self.subscribe(participant)
        self.send_ui(participant=participant["id"])


    def on_participant_left(self, participant, reason):
        print(f"on_participant_left " + participant["id"] + " " + reason) 
        count = 0
        participants = self._client.participants()
        for key, value in participants.items():
            if key == participant["id"] or key == "local":
                continue
            count += 1
        if count == 0:
            print("quitting... " + participant["id"] + " left. ")
            self._app_quit = True  


    def on_app_message(self, message, sender) :
        try :
            funct   = message.get("message", {})
            name    = funct.get("name"   , "")
            args    = funct.get("args"   , [])
            if name in self._function_map:
                self._function_map[name](*args)
                print(f"Received message from {sender}: {message}")
            else:
                print(f"Received invalid message from {sender}: {message}")
        except Exception:
            print(f"Received invalid message from {sender}: {message}")
            return

    def delay(self, value):
        self._delay            = value
        self._audio_buffer.delay( self._delay )
        self._video_buffer.delay( self._delay )

    def send_ui(self, participant=None):
        payload = { "ui": [
            {"type" : "slider",
            "name"    : "delay",
            "value" : self._delay,
            "min"     : ASSUMED_LATENCY,
            "max"     : self._max_delay,
            "step"    : .050}]}

        print(f"sending ui - {participant} {json.dumps(payload)}")  
        self._client.send_app_message( { "message" : payload })

    def _find_bird(self, participants): 
        for key, participant in participants.items():
            if self._is_bird(participant) :    
                return participant
        return None
        
    def _is_bird(self, participant) :
        return not ( participant["info"]["isLocal"] == True  or participant["info"]["userId"] == "human" or  participant["info"]["userId"] == "bot" )

    def subscribe(self, participant)  :
        try : 
            if (participant is not None and (not self._subscribed) ) :
                print(f"Connected to " + participant["info"]["userName"]  + " " + participant["id"] ) 
                self._subscribed = True
                self._client.set_audio_renderer(participant["id"], self.on_audio_frame )
                self._client.set_video_renderer(participant["id"], self.on_video_frame )

        except Exception as e:
            print(f"An error occurred: {e}")
            self._app_quit = True

    def __init__(self):

        self._app_quit    = False
        self._subscribed  = False
        self._function_map = {"delay" : self.delay}
        self._max_delay    = 5.0

        self._speaker_device = Daily.create_speaker_device( "speaker",sample_rate=48000,channels=1)
        Daily.select_speaker_device("speaker")

        self._microphone   = Daily.create_microphone_device("mic", sample_rate=48000 , channels=1 , non_blocking=True)
        self._camera       = Daily.create_camera_device("cam", width=360, height=640, color_format="RGBA")
        self._audio_buffer = AudioBuffer( self._max_delay, maxsize=15)
        self._video_buffer = VideoBuffer(self._camera , self._max_delay)
        self.delay(self._max_delay)

        self._client = CallClient(self)
        self._client.update_subscription_profiles({ "base": {"camera": "subscribed", "microphone": "subscribed"}})
        self._client.update_inputs({
            "camera"    : { "isEnabled": True, "settings": {"deviceId": "cam" } },
            "microphone": { "isEnabled": True, "settings": {"deviceId": "mic" } }
        })

        self._init_time  = int(time.time())
        def write_video():
            while not self._app_quit:
                if ( (not self._subscribed) and ( int(time.time()) - self._init_time > 60) ) :
                    print( "quiting... participant did not join.")
                    self._app_quit = True
                else :
                    data = self._video_buffer.getFromQueue()  
                    if data : 
                        self._camera.write_frame(  data.frames() )
                    gc.collect()

        self.__video_thread = threading.Thread(target=write_video)
        self.__video_thread.start()

        def write_audio():
            while not self._app_quit:
                data = self._audio_buffer.getFromQueue()
                if data :
                    self._microphone.write_frames( data.frames() )

        self.__audio_thread = threading.Thread(target=write_audio)
        self.__audio_thread.start()

    def run(self, url, token):
        self._client.join(url, meeting_token=token, completion=self.on_joined)
        self.__video_thread.join()
        self.__audio_thread.join()

    def leave(self):
        self._app_quit = True
        self._client.leave()
        self._client.release()

    def on_audio_frame(self, participant_id, audio_data  ):
        if self._app_quit:
            return
        if audio_data :
            self._audio_buffer.append( audio_data ) 

    def on_video_frame(self, participant_id, video_frame): 
        if self._app_quit:
            return
        if video_frame : 
            self._video_buffer.append( video_frame ) 
        

def main():
    (url, token, delay) =  configure()

    print(f"main() echo_bot {delay} msec. : {url} ")

    Daily.init()
    bot = EchoBot()
    bot.delay( int(delay)/1000.0)

    try: 
        bot.run(url, token)

    except Exception as e:
        bot._app_quit = True
        print(f"An error occurred: {e}")

    finally:
        bot.leave()

    Daily.deinit()

    print("Exited. process complete")
    
if __name__ == "__main__":
    main()




