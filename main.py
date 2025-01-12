import sys
import time
import traceback
import os
import string
import json
from rapidfuzz import fuzz, process
#from TTS.api import TTS
from gtts.tts import gTTS
import pydub
from pydub import playback
import asyncio
import threading
import re
import whisper
import speech_recognition as sr
from EdgeGPT import Chatbot as Bing, ConversationStyle
from Bard import Chatbot as Bard

bot = None
bard_bot = None
bing_bot = None
bing_cookies: dict = {}
try:
	with open("cookies.json", "r") as f:
		bing_cookies = json.load(f)
except:
	pass
bard_token: str = ""
try:
	with open("bard.txt", "r") as f:
		bard_token = f.read()
except:
	pass
if not bard_token and not bing_cookies:
	print("Couldn't find the required information for any of the supported services, exiting...")
	sys.exit(0)

def initialize_chat_bot():
	"""Creates an instance of Chatbot."""
	global bing_bot, bard_bot
	if bing_cookies:
		try:
			bing_bot = Bing(cookies=bing_cookies)
			print("Using Bing Chat")
		except Exception as e:
			print(f"Couldn't initialize Bing Chat: {e}")
	if bard_token:
		try:
			bard_bot = Bard(session_id=bard_token)
			print("Using Google Bard")
		except Exception as e:
			print(f"Couldn't initialize Google Bard: {e}")
	if not bing_bot and not bard_bot:
		print("None of the services could be initialized. Exiting...")
		sys.exit(0)

async def reset_chat_bot():
	global bing_bot, bard_bot, bot
	if bot:
		if isinstance(bot, Bing):
			await bing_bot.reset()
		elif isinstance(bot, Bard):
			bard_bot = Bard(bard_token)

initialize_chat_bot()

recognizer = sr.Recognizer()

#Initialize TTS
#tts = TTS(model_name="tts_models/en/ljspeech/fast_pitch", model_path = ".cache/TTS/fast_pitch/model_file.pth", config_path = ".cache/TTS/fast_pitch/config.json", vocoder_path=".cache/TTS/vocoder_hifigan_v2/model_file.pth", vocoder_config_path=".cache/TTS/vocoder_hifigan_v2/config.json")

model = whisper.load_model("base", download_root = '.cache/whisper/')

# A list of dictionaries needed to trigger services.
wake_list = [
	{"sentence": "Hey Bing", "service": bing_bot},
	{"sentence": "Hey Bard", "service": bard_bot},
]
current_wake_sentence: str = ""

def clean_str(text: str) -> str:
	text = strip_emojis(text)
	text = strip_punctuation(text)
	text= text.lstrip()
	text = text.rstrip()
	text = text.lower()
	return text

def get_wake_sentence(phrase: str) -> tuple:
	"""Checks the spoken phrase against wake_sentence.
	Returns the spoken phrase, if the assessment passes, so that later it can be used for prompting the bot without waiting."""
	global bot, current_wake_sentence
	if phrase == "": return None
	for wake_info in wake_list:
		ratio = fuzz.ratio(wake_info["sentence"], phrase[0:len(wake_info["sentence"])])
		if ratio >= 70:
			if not wake_info["service"]:
				speak("The chosen service has not been initialized")
				return ()
			current_wake_sentence = phrase[0:len(wake_info["sentence"])]
			bot = wake_info["service"]
			return (phrase, ratio)
	speak("I heard, " + phrase +". Which is not a wake up word for me.")
	return ()

def strip_punctuation(text: str) -> str:
	"""Strips all punctuation symbols from the given string"""
	return text.translate(str.maketrans('', '', string.punctuation))

def strip_emojis(text: str) -> str:
	emoji_pattern = re.compile("["
		u"\U0001F600-\U0001F64F"  # emoticons
		u"\U0001F300-\U0001F5FF"  # symbols & pictographs
		u"\U0001F680-\U0001F6FF"  # transport & map symbols
		u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
		u"\U00002702-\U000027B0"
		u"\U000024C2-\U0001F251"
		"]", flags=re.UNICODE
	)
	text = emoji_pattern.sub(r'', text)
	return text

def is_question(text: str) -> bool:
	"""Checks to make sure the text ends with a question by removing all the emoji characters, then stripping the trailing white spaces."""
	text = strip_emojis(text)
	text = text.rstrip()
	return text.endswith("?")

def strip_wake_sentence(spoken_sentence: str) -> str:
	"""Strips wake_sentence from spoken_sentence and returns it"""
	
	spoken_sentence = spoken_sentence[len(current_wake_sentence):]
	spoken_sentence = spoken_sentence.lstrip()
	return spoken_sentence

def _load_play_audio(file: str):
	"""Loads and plays an audio file. Must be seprated from the `play_audio` function, so that both loading and playing procedure can be in one single thread. Otherwise, the none blocking mode will not work."""
	sounddata = pydub.AudioSegment.from_file(file, format=file.split(".")[-1])
	playback.play(sounddata)

def play_audio(file: str, blocking: bool = False):
	"""Plays an audio file.
	In order for the none blocking mode to work, the actual logic of loading and playing sounds is moved to the `_load_play_audio` function. If loading and playing of audio files are seprated in different threads, the none blocking mode will not work as expected"""
	if blocking:
		_load_play_audio(file)
	else:
		t = threading.Thread(target=_load_play_audio, args=[file])
		t.daemon = True
		t.start()

def speak(text: str, blocking: bool = True):
	#tts.tts_to_file(text, speed=2.0, file_path="tts_output.mp3")
	speech = gTTS(text=text, tld="ca")
	speech.save("tts_output.mp3")
	play_audio("tts_output.mp3", blocking=blocking)
	os.remove("tts_output.mp3")

async def get_trigger(source: sr.Microphone):
	global bot
	play_audio("sounds/get_trigger.mp3", True)
	while True:
		try:
			recognizer.energy_threshold = 1000
			try:
				audio = recognizer.listen(source, 4)
			except sr.exceptions.WaitTimeoutError:
				continue
			play_audio("sounds/processing.mp3")
			try:
				with open("audio.mp3", "wb") as f:
					f.write(audio.get_wav_data())
				
				result = model.transcribe("audio.mp3", initial_prompt = "Hey ")
				os.remove("audio.mp3")
				phrase = result["text"]


				try:
					spoken_sentence, ratio = get_wake_sentence(phrase=phrase)
				except (ValueError, TypeError):
					#Play the get trigger audio so the user knows they can speak
					play_audio("sounds/get_trigger.mp3")
					continue
				processed_sentence = clean_str(spoken_sentence)
				if processed_sentence != "":
					processed_sentence = strip_wake_sentence(processed_sentence)
					if processed_sentence == "":
						break
					elif fuzz.ratio(processed_sentence, "new topic") >= 70:
						await reset_chat_bot()
						#Announce that there's going to be a new topic from now on so that user won't continue the last one.
						speak("New topic. What can I do for you?")
						break
					else:
						#Something is spoken after the wake up sentence, so we are going to ask about it from bing.
						spoken_sentence = strip_wake_sentence(spoken_sentence)
						response_params = process_response(await get_response(spoken_sentence))
						if response_params["question"]:
							#A question is asked, so move back to main to get a prompt.
							break
						else:
							#Play the get trigger audio so the user knows they can speak
							play_audio("sounds/get_trigger.mp3")
			except IndexError:
				speak("Your cookie information for Google Bard appears to be invalidated. Please renew the cookie value and restart the program. If you need help, take a look at the read me file.")
				#Play the get trigger audio so the user knows they can speak
				play_audio("sounds/get_trigger.mp3")
				continue
			except (ConnectionResetError, ConnectionAbortedError, ConnectionError):
				# Connection error of some kind
				speak("There appears to be an issue with your connection. Please check the connection and try again")
				#Play the get trigger audio so the user knows they can speak
				play_audio("sounds/get_trigger.mp3")
				continue
			except Exception as e:
				speak("There was an error transcribing your audio. Please try again.")
				#Play the get trigger audio so the user knows they can speak
				play_audio("sounds/get_trigger.mp3")
				continue
		except KeyboardInterrupt:
			await quit()

async def main():
	global bot
	with sr.Microphone() as source:
		recognizer.dynamic_energy_threshold = False
		await get_trigger(source=source)
		#recognizer.adjust_for_ambient_noise(source, 0.5)
		while True:
			try:
				#recognizer.energy_threshold = 300
				play_audio("sounds/prompt.mp3", True)
				
				try:
					audio = recognizer.listen(source, 5)
				except sr.exceptions.WaitTimeoutError:
					await get_trigger(source)
					continue

				play_audio("sounds/processing.mp3")
				try:
					with open("audio_prompt.mp3", "wb") as f:
						f.write(audio.get_wav_data())
					result = model.transcribe("audio_prompt.mp3")
					os.remove("audio_prompt.mp3")
					user_input = result["text"]
					if fuzz.ratio(user_input, "new topic") >= 70:
						await reset_chat_bot()
						speak("New topic. What can I do for you?")
						continue
				except Exception as e:
					print("Error transcribing audio: {0}".format(e))
					continue
				response_params = process_response(await get_response(user_input=user_input))
				if not response_params["question"]:
					#No question is asked, so move on to waiting for the wake up sentence again.
					await get_trigger(source=source)
			except KeyboardInterrupt:
				await quit()

async def get_response(user_input: str) -> str:
	play_audio("sounds/requesting.mp3")
	bot_response = "Sorry, service returned no response"
	if isinstance(bot, Bing):
		result = await bot.ask(prompt=user_input, conversation_style=ConversationStyle.precise)
		for message in result["item"]["messages"]:
			if message["author"] == "bot":
				bot_response = message["text"]
		bot_response = re.sub('\[\^\d+\^\]', '', bot_response)
	elif isinstance(bot, Bard):
		result = bot.ask(user_input)
		bot_response = result["content"]
	return bot_response

def process_response(response: str):
	speak(response)
	return {
		"question": is_question(response)
	}

async def quit():
	print("exiting...")
	if bot and isinstance(bot, Bing):
		bot = None
		await bing_bot.close()
	sys.exit(0)

if __name__ == "__main__":
	asyncio.run(main())
