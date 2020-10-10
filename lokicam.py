print("loading")

import argparse
import cv2
import datetime
from dotenv import load_dotenv
import imutils
import os
from picamera.array import PiRGBArray
from picamera import PiCamera
import telegram
import time

ap = argparse.ArgumentParser()
ap.add_argument("--interactive", action="store_true", default=False, help="enable interactive mode")
ap.add_argument("--min-area", type=int, default=1000, help="minimum area for motion detection")
ap.add_argument("--threshold", type=int, default=10, help="brightness change threshold for motion detection")
ap.add_argument("--report-frames", type=int, default=10, help="consecutive frames with motion detected to trigger a report")
ap.add_argument("--normalize-frames", type=int, default=100, help="consecutive frames with motion detected which reset what is considered 'normal'")
args = vars(ap.parse_args())

load_dotenv()

bot = telegram.Bot(token=os.getenv("TELEGRAM_BOT_TOKEN"))
chatId = os.getenv("TELEGRAM_CHAT_ID")

camera = PiCamera()
camera.resolution = (640, 480)
camera.framerate = 4 # originally 32
rawCapture = PiRGBArray(camera, size=(640, 480))

print("warming up")
time.sleep(2)

basis = None
skip = max(5, int(2 / camera.framerate)) # 2 seconds
minArea = args["min_area"]
thresholdValue = args["threshold"] # default 10, original used 25 but couldn't pick up dark objects
detectedFrames = []
capture = 0

def write_video(filename, frames):
    print("writing {}".format(filename))
    video = cv2.VideoWriter(
            filename,
            cv2.VideoWriter_fourcc(*'mp4v'),
            camera.framerate,
            camera.resolution,
            )
    for f in frames:
        video.write(f)
    video.release()

print("starting capture")
for cameraFrame in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
    # grab the raw numpy array for the image
    frame = cameraFrame.array

    if frame is None:
        break

    #frame = imutils.resize(frame, width=500)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (21, 21), 0)

    if basis is None:
        skip -= 1
        if skip <= 0:
            basis = gray
        rawCapture.truncate(0)
        print("warming up; skipping frame")
        continue

    frameDelta = cv2.absdiff(basis, gray)
    thresh = cv2.threshold(frameDelta, thresholdValue, 255, cv2.THRESH_BINARY)[1]

    thresh = cv2.dilate(thresh, None, iterations=2)
    contours = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = imutils.grab_contours(contours)

    changeDetected = False
    for c in contours:
        area = cv2.contourArea(c)
        if area < minArea:
            continue
        else:
            print("change area {}".format(area))

        changeDetected = True
        (x, y, w, h) = cv2.boundingRect(c)
        cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
    
    cv2.putText(frame, datetime.datetime.now().strftime("%A %d %B %Y %I:%M:%S%p"),
            (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)

    if changeDetected:
        detectedFrames.append(frame.copy())
        if len(detectedFrames) == args["report_frames"]:
            # report!
            filename = "capture{}.mp4".format(capture)
            capture += 1
            write_video(filename, detectedFrames)
            with open(filename, 'rb') as videoFile:
                result = bot.send_video(
                        chat_id=chatId,
                        video=videoFile,
                        caption="Loki detected!",
                        )
                print("telegram result: {}".format(result))
            #detectedFrames = []
        else:
            print("have {} detected frames".format(len(detectedFrames)))
            if len(detectedFrames) > 100:
                print("setting current frame as new basis")
                basis = gray
                detectedFrames = []
    else:
        basis = gray
        if len(detectedFrames) > 0:
            print("tossing {} detected frames".format(len(detectedFrames)))
            detectedFrames = []

    if args["interactive"]:
        cv2.imshow("Frame", frame)
        cv2.imshow("Thresh", thresh)
        cv2.imshow("Delta", frameDelta)
        key = cv2.waitKey(1) & 0xff
        if key != 255:
            print("key: {}".format(key))
        if key == 82:
            thresholdValue += 1
            print("new threshold: {}".format(thresholdValue))
        if key == 84:
            thresholdValue -= 1
            print("new threshold: {}".format(thresholdValue))
        if key == ord("q"):
            break

    #print("next frame")
    rawCapture.truncate(0)

