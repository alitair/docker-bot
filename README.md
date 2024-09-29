To run locally, create a .env file


<code>BIRDCONV_SERVER=http://localhost:5173
 API_KEY=your birdconv api key
 APP_HOST=http://0.0.0.0:7860
 RUN_AS_PROCESS=true</code>

Start the webserver locally on port 5173

<code>npm run dev</code>

Start the bot server:

<code>python server.py</code>

To run on fly create a fly.env file like the sample.env


<code>fly launch
 fly deploy
 cat fly.env | fly secrets import</code>
