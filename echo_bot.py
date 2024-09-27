import threading
import queue
import time
import json
from   daily import *
from   runner import configure
from PIL import Image


class EchoBot(EventHandler):

    # each frame is BUFFER seconds worth of audio
    CHANNELS = 2
    BUFFER = .01 * CHANNELS


    def on_call_state_updated(self,state):
        if state == "left":
            self._app_quit = True

    def on_error(self, message):
        print(f"Error: {message}")
        self._app_quit = True

    def on_participant_joined(self, participant):
        self.send_ui(participant=participant["id"])

    def on_participant_left(self, participant, reason):

        count = 0

        participants = self._client.participants()

        for key, value in participants.items():
            if key == participant["id"] or key == "local":
                continue
            count += 1

        if count == 0:
            self.leave() 
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
        self._frame_size       = int(self._sample_rate * EchoBot.BUFFER)
        self._blank_frame      = bytes([0] * self._frame_size)
        self._ideal_queue_size = max( int( (self._delay-.1)/EchoBot.BUFFER), 1 )


    def send_ui(self, participant=None):
        
        payload = { "ui": [
            {"type" : "slider",
            "name"    : "delay",
            "value" : self._delay,
            "min"     : 0,
            "max"     : 5,
            "step"    : .5}]}

        print(f"sending ui - {participant} {json.dumps(payload)}")  
        self._client.send_app_message( { "message" : payload })
        # self._client.send_prebuilt_chat_message(json.dumps(payload),"bot")


    def __init__(self):


        self._function_map = {
            "delay" : self.delay
        }

        self._sample_rate = 48000

        self.delay(2)


        self._framerate = 10
        self._width = 540
        self._height = 540
        self._image = Image.new('RGB', (self._width, self._height), (0, 0, 0))
        self._camera = Daily.create_camera_device("my-camera",width=self._image.width,height=self._image.height, color_format="RGB")

        self._client = CallClient(self)
        self._client.update_subscription_profiles({
            "base": {
                "camera": "unsubscribed",
                "microphone": "subscribed"
            }
        })

        self._mic_device     = Daily.create_microphone_device("my-mic", sample_rate=self._sample_rate , channels=EchoBot.CHANNELS)
        self._speaker_device = Daily.create_speaker_device("my-speaker", sample_rate=self._sample_rate , channels=EchoBot.CHANNELS)
        Daily.select_speaker_device("my-speaker")

        self.client_settings = {
            "inputs": {
                "camera": {
                    "isEnabled": True,
                    "settings": {
                        "deviceId": "my-camera"
                    }
                },
                "microphone": {
                    "isEnabled": True,
                    "settings": {
                        "deviceId": "my-mic"
                    }
                }
            }
        }

        self._app_quit = False
        self._app_error = None

        self._buffer_queue = queue.Queue()

        self._start_send_image_event = threading.Event()
        self._thread_send_image = threading.Thread(target=self.send_image)
        self._thread_send_image.start()

        self._start_receive_event = threading.Event()
        self._thread_receive      = threading.Thread(target=self.receive_audio)
        self._thread_receive.start()

        self._start_send_event = threading.Event()
        self._thread_send       = threading.Thread(target=self.send_audio)
        self._thread_send.start()


    def run(self, url, token):
        self._client.join(url, meeting_token=token, client_settings=self.client_settings, completion=self.on_joined)
        self._thread_send_image.join()
        self._thread_receive.join()
        self._thread_send.join()


    def on_joined(self, data, error):
        if error:
            print(f"Unable to join meeting: {error}")
            self._app_error = error

        self._start_send_image_event.set()
        self._start_receive_event.set()
        self._start_send_event.set()

        self.send_ui()
    

    def leave(self):
        self._app_quit = True
        self._thread_send_image.join()
        self._thread_receive.join()
        self._thread_send.join()
        self._client.leave()
        self._client.release()


    def receive_audio(self):
        self._start_receive_event.wait()
        print("starting receive audio thread")

        if self._app_error:
            print("Unable to receive audio!")
            return

        while not self._app_quit:

            if self._buffer_queue.qsize() > self._ideal_queue_size :
                self._buffer_queue.get(timeout=.5)

            buffer = self._speaker_device.read_frames(self._frame_size)
            if buffer:
                self._buffer_queue.put(buffer) 

    def send_audio(self):
        self._start_send_event.wait()
        print("starting send audio thread")

        if self._app_error:
            print("Unable to send audio!")
            return

        while not self._app_quit:
            try:
                if self._delay <= 0 :
                    self._mic_device.write_frames(self._blank_frame)
                elif self._buffer_queue.qsize() > self._ideal_queue_size - 1:
                    buffer = self._buffer_queue.get(timeout=EchoBot.BUFFER) 
                    if buffer:
                        self._mic_device.write_frames(buffer)
                else :
                    time.sleep(EchoBot.BUFFER)
            except queue.Empty:
                continue

    def send_image(self):
        self._start_send_image_event.wait()
        print("starting send_image thread")

        if self._app_error:
            print(f"Unable to send!")
            return

        sleep_time = 1.0 / self._framerate
        image_bytes = self._image.tobytes()

        while not self._app_quit:
            self._camera.write_frame(image_bytes)
            time.sleep(sleep_time)


def main():
    (url, token) =  configure()

    Daily.init()
    bot = EchoBot()

    try: 
        bot.run(url, token)

    finally:
        bot.leave()

    Daily.deinit()

    print("Exiting...")
    
if __name__ == "__main__":
    main()




