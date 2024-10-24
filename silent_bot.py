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

class BufferedAudioData :
    def __init__(self, data) :
        self.data        = data
        self.silent      = False
        self.dt          = data.num_audio_frames / data.sample_rate
    
    def frames(self) :
        # RETURN SILENT FRAMES
        # return self.data.audio_frames
        # if self.silent :
        return bytes([0] * int(self.data.num_audio_frames * self.data.num_channels * self.data.bits_per_sample / 8) )
        # else :  
        #     return self.data.audio_frames
        
class MediaBuffer : 

    def __init__(self) :
        self.buffer       = []
        self.elapsed_time = 0.0
        self._delay       = 0.0
        self.read_index   = 0
        self.buffer_ready = False

    def pop(self) :
        if not self.buffer_ready :
            self.read_index = self._find_index()
            self.buffer_ready = True

        return self.buffer.pop( self.read_index )
    
    def _find_index(self) :

        index   = len(self.buffer) - 1
        if ( self._delay <= 0.0 ) :
            return index

        delta_t = 0.0
        while (index >= 0) :
            delta_t += self.buffer[index].dt
            if delta_t > self._delay :
                break
            index -= 1
        return index
        
class AudioBuffer(MediaBuffer) :

    def __init__(self) :
        super().__init__()

    def append(self, data) :
        buffered_audio_data = BufferedAudioData( data )

        if self._delay <= 0.0 :
            buffered_audio_data.silent = True

        self.elapsed_time += buffered_audio_data.dt
        self.buffer.append( buffered_audio_data )


    def delay(self, value):
        self._delay      = max(0, value - .15) # 150ms latency
        self.read_index  = max(0, self._find_index() - 1)
        for i in range(0,self.read_index) :
            self.buffer[i].silent = True


class BufferedVideoData :
    def __init__(self, data, dt) :
        self.data   = data
        self.timestamp_us = data.timestamp_us
        self.dt           = dt   

    def width(self) :
        return self.data.height
    
    def height(self) :
        return self.data.width

    def frames(self) :
        image         = np.array( Image.frombytes(self.data.color_format, (self.data.width, self.data.height), self.data.buffer) ) 
        rotated_frame = cv2.rotate( image , cv2.ROTATE_90_CLOCKWISE)
        image         = Image.fromarray(rotated_frame)
        # BLANK OUT THE BUFFER
        # buffer = image.tobytes()
        buffer = bytes([0] * len(self.data.buffer))
        return buffer
    
class VideoBuffer(MediaBuffer) : 
    def __init__(self) :
        super().__init__()

    def delay(self, value):
        self._delay = value
        self.read_index  = max(0, self._find_index() - 1)
        for i in range(0,self.read_index) :
            self.buffer[i].data = self.buffer[self.read_index].data

    def append(self, data ) :
        if (len(self.buffer) == 0) :
            buffered_video_data = BufferedVideoData( data,  0.0 )
        else :
            buffered_video_data = BufferedVideoData( data, (data.timestamp_us - self.buffer[ len(self.buffer) -1 ].timestamp_us)/1_000_000.0 )

        self.elapsed_time += buffered_video_data.dt
        self.buffer.append( buffered_video_data )




class SilentBot(EventHandler):

    def on_call_state_updated(self,state):
        print(f"Call state updated {state}")
        if state == "left":
            self._app_quit = True

    def on_error(self, message):
        print(f"Error: {message}")
        self._app_quit = True

    def on_joined(self, data, error):
        print(f"on_joined {error}")

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
            self._app_quit = True  


    def on_app_message(self, message, sender) :
        # NO MESSAGE HANDLING
        # try :
        #     funct   = message.get("message", {})
        #     name    = funct.get("name"   , "")
        #     args    = funct.get("args"   , [])
        #     if name in self._function_map:
        #         self._function_map[name](*args)
        #         print(f"Received message from {sender}: {message}")
        #     else:
        #         print(f"Received invalid message from {sender}: {message}")
        # except Exception:
        print(f"Received invalid message from {sender}: {message}")
        return

    def delay(self, value):
        self._delay            = value
        self._audio_buffer.delay( self._delay )
        self._video_buffer.delay( self._delay )


    def send_ui(self, participant=None):
        print(f"send_ui [no ui] {participant}")
        # NO UI
        # payload = { "ui": [
        #     {"type" : "slider",
        #     "name"    : "delay",
        #     "value" : self._delay,
        #     "min"     : 0,
        #     "max"     : self._max_delay,
        #     "step"    : .5}]}

        # print(f"sending ui - {participant} {json.dumps(payload)}")  
        # self._client.send_app_message( { "message" : payload })


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
                print(f"Setting audio and video renderer to " + participant["info"]["userName"]  + " " + participant["id"] ) 
                self._subscribed = True
                self._client.set_audio_renderer(participant["id"], self.on_audio_frame )
                self._client.set_video_renderer(participant["id"], self.on_video_frame )

        except Exception as e:
            print(f"An error occurred: {e}")
            # import traceback
            # traceback.print_exc()

    def __init__(self):

        self._subscribed  = False
        self._audio_buffer = AudioBuffer()
        self._video_buffer = VideoBuffer()
        # SET DELAY TO 0
        self.delay(0)
        self._function_map = {"delay" : self.delay}

        # LOWER THE MAX DELAY
        self._max_delay    = 2.0
        self._client = CallClient(self)
        self._client.update_subscription_profiles({ "base": {"camera": "subscribed", "microphone": "subscribed"}})
        self._camera     = None
        self._microphone = None 
        self._app_quit   = False
        self._registered = False

        def wait_until_done():
            while not self._app_quit:
                time.sleep(0.1)

        self.__thread = threading.Thread(target=wait_until_done)
        self.__thread.start()

    def run(self, url, token):
        self._client.join(url, meeting_token=token, completion=self.on_joined)
        self.__thread.join()

    def leave(self):
        self._app_quit = True
        self._client.leave()
        self._client.release()

    def on_audio_frame(self, participant_id, audio_data  ):
        if self._app_quit:
            return
        
        if audio_data :
            if (self._microphone is None) :
                self._microphone = Daily.create_microphone_device("mic", sample_rate=audio_data.sample_rate , channels=audio_data.num_channels)

            self._audio_buffer.append( audio_data ) 

            if self._audio_buffer.elapsed_time >= self._max_delay + 2.0 :
                self._microphone.write_frames(self._audio_buffer.pop().frames())

    def on_video_frame(self, participant_id, video_frame): 
        if self._app_quit:
            return

        if video_frame:
            if (self._camera is None and self._video_buffer.elapsed_time >=2.0 ) :
                self._camera = Daily.create_camera_device("cam",width=video_frame.height, height=video_frame.width, color_format=video_frame.color_format)
                print( f"self._camera {self._camera.width} {self._camera.height} {self._camera.color_format}" )

            if (self._registered == False) :
                self.update_inputs()

            self._video_buffer.append( video_frame ) 

            if self._video_buffer.elapsed_time >= self._max_delay + 2.0 :
                self._camera.write_frame(  self._video_buffer.pop().frames() )


    def update_inputs(self) :
        if (self._camera is not None and  self._microphone is not None ) :
            self._registered = True
            self._client.update_inputs({
                "camera"    : { "isEnabled": True, "settings": {"deviceId": "cam" } },
                "microphone": { "isEnabled": True, "settings": {"deviceId": "mic" } }
            })

def main():
    (url, token, delay) =  configure()

    print(f"silent_bot: {url} {token} {delay}")

    Daily.init()
    bot = SilentBot()
    bot.delay( int(delay)/1000.0)

    try: 
        bot.run(url, token)

    except Exception as e:
        print(f"An error occurred: {e}")

    finally:
        bot.leave()

    Daily.deinit()

    print("Exited.")
    
if __name__ == "__main__":
    main()




