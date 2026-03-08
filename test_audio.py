import logging
import time
from src.speech.announcer import Announcer
from src.config import init_config

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("test_audio")

def test():
    config = init_config()
    print(f"Configured device: {config.tts.device}")
    
    announcer = Announcer(
        voice_model=config.tts.voice_model,
        volume=config.tts.volume
    )
    
    print("Initializing TTS...")
    announcer.init_tts()
    
    if not announcer.voice:
        print("Failed to initialize TTS voice")
        return

    print("Queuing announcement...")
    success = announcer.announce("Testing audio output. Hello world.")
    if not success:
        print("Failed to queue announcement")
        return
    
    # Wait for playback
    print("Waiting for playback to complete (15s)...")
    for i in range(15):
        time.sleep(1)
        if i % 5 == 0:
            print(f"Still waiting... {i}s")
    
    print("Stopping announcer...")
    announcer.stop()
    print("Done.")

if __name__ == "__main__":
    test()
