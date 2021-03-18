#face detection dependencies
import cv2
import numpy as np

#TCP/IP socket communication dependencies
import socket
from threading import Thread
import threading
import time

#sys lib for checking a platform (OS)
from sys import platform

#support libraries for image packing
import struct
import pickle

#arguments parser for IP address enter
import argparse

def str2bool(v):
    if isinstance(v, bool):
       return v
    if v.lower() in ('yes', 'true', 't', 'y', '1'):
        return True
    elif v.lower() in ('no', 'false', 'f', 'n', '0'):
        return False
    else:
        raise argparse.ArgumentTypeError('Boolean value expected.')

parser = argparse.ArgumentParser(description='set the IP address.')
parser.add_argument('--IP', type=str, help='set the IP address of the rPi (server device)', default=socket.gethostname() )
parser.add_argument('--display', type=str2bool, help='set the display flag', nargs='?', const=True, default=False)
parser.add_argument('--fps', type=float, help='set the fps of rec video', default=10.0)
parser.add_argument('--streaming', type=int, help='set the streaming limit if hcsr04 detected someone', default=10)
parser.add_argument('--mcast', type=str2bool, help='run on multicast mode', nargs='?', const=True, default=False)

args = parser.parse_args()

#RPi lib for distance measurement usecase
bRpiUsed = True
try:
    import RPi.GPIO as GPIO
except ModuleNotFoundError:
    bRpiUsed = False

bDistanceDetection = True
if True == bRpiUsed:
    # GPIO Mode (BOARD / BCM)
    GPIO.setmode(GPIO.BCM)

    #set GPIO Pins
    GPIO_TRIGGER = 18
    GPIO_ECHO = 24

    #set GPIO direction (IN / OUT)
    GPIO.setup(GPIO_TRIGGER, GPIO.OUT)
    GPIO.setup(GPIO_ECHO, GPIO.IN)

    StartTime = time.time()
    StopTime = time.time()

    def distance():
        # set Trigger to HIGH
        GPIO.output(GPIO_TRIGGER, True)
    
        # set Trigger after 0.01ms to LOW
        time.sleep(0.00001)
        GPIO.output(GPIO_TRIGGER, False)
    
        # save StartTime
        while GPIO.input(GPIO_ECHO) == 0:
            StartTime = time.time()
    
        # save time of arrival
        while GPIO.input(GPIO_ECHO) == 1:
            StopTime = time.time()
    
        # time difference between start and arrival
        TimeElapsed = StopTime - StartTime
        # multiply with the sonic speed (34300 cm/s)
        # and divide by 2, because there and back
        distance = (TimeElapsed * 34300) / 2
    
        return distance

    def HCSR04_loop():
        global bDetected
        bDetected = False
        itterations = 0 #til itterationLimit
        itterationLimit = args.streaming
        distanceLimit = 80.0
        while bDistanceDetection:
            dist = distance()
            print ("Measured Distance = %.1f cm" % dist)
            if(dist < distanceLimit):
                bDetected = True
            if(True == bDetected):
                itterations += 1
            if(itterations == itterationLimit):
                itterations = 0
                bDetected = False
            print("HCSR04_loop thread :: detected movement = ",str(bDetected) )
            time.sleep(1)
        GPIO.cleanup()

#socket server's IP address & port 
port = 21000

bMulticast = args.mcast 
if(False == bMulticast):
    host = str(args.IP)
else:
    MCAST_GRP = "224.0.0.251"
    host = MCAST_GRP
    MULTICAST_TTL = 2

if(False == bMulticast):
    #socket initialisation
    clients = set()
    clients_lock = threading.Lock()

    serversock = socket.socket()
    serversock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    serversock.bind(('',port))
    serversock.listen()
else:
    serversock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    serversock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, MULTICAST_TTL)

if platform != "win32":
    print("IP: ")
    print(serversock.getsockname() )

th = []

#encode (jpeg compression) quality
encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 50]

#face detection classifier
face_cascade = cv2.CascadeClassifier('haarcascade_frontalface_default.xml')
 
#WebCam handler
if platform == "linux" or platform == "linux2":
    cap = cv2.VideoCapture(0)
elif platform == "win32":
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(3, 320)
cap.set(4, 240)

#initialisation for data packing
ret, frame = cap.read()
result, framePacked = cv2.imencode('.jpg', frame, encode_param)

bClientConnection = True

def listener(client, address):
    global bDetected
    # Atribut global govori da je u pitanju globalna promenljiva, te da ne instancira
    # novu lokalnu promenljivu nego njene vrednosti očitava ‘spolja’
    global bSndMsg
    bSndMsg = False
    print ("\nAccepted connection from: ", address,'\n')
    with clients_lock:
        clients.add(client)

    while bClientConnection:
        if bDetected == True:
            if(bSndMsg == True):
                try:
                    client.sendall(framePacked)
                    bSndMsg = False
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    break
    
    print("\nBroken connection from: ", address, "\n")
    client.close()
    clients.remove(client)

def clientReceivement():
    print ("\nWaiting for new clients...\n")
    while bClientConnection:
        try:
           (client, address) = serversock.accept()
        except OSError:
            break

        th.append(Thread(target=listener, args = (client,address)) )
        th[-1].start()

bRecordVideo = True

from datetime import datetime
import os
mypath = 'videos/'
if not os.path.isdir(mypath):
   os.makedirs(mypath)

def VideoWriting():
    global frame
    global bWriteVideo
    global bDetected
    bDetected = False
    bFirstTime = True
    bWriteVideo = False
    out = cv2.VideoWriter()
    fourcc = cv2.VideoWriter_fourcc('M','J','P','G')

    while bRecordVideo:
        if(True == bFirstTime and True == bDetected and True == bWriteVideo):
            date_time = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
            fileName = mypath + 'video_' + date_time + '.avi'
            out = cv2.VideoWriter(fileName, fourcc, args.fps, (int(cap.get(3)), int(cap.get(4)))) 
            bFirstTime = False
        if(True == bWriteVideo):
            out.write(frame)
            bWriteVideo = False
        if(False == bDetected):
            bFirstTime = True
            out.release()
    if(out.isOpened() ):
        out.release()

if True == bRpiUsed:
    th.append(Thread(target=HCSR04_loop))
    th[-1].start()

if(False == bMulticast):
    th.append(Thread(target=clientReceivement) )
    th[-1].start()

th.append(Thread(target=VideoWriting) )
th[-1].daemon = True
th[-1].start()

bDetected = not bRpiUsed
bSndMsg = False
bWriteVideo = False
while True:
    try:
        ret, frame = cap.read()

        if(False == ret or frame is None):
            print("Frame doesn't exist")
            break

        if True == bDetected:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 
                scaleFactor=1.3, 
                minNeighbors=5)
            for(x, y, w, h) in faces:
                cv2.rectangle(frame, (x,y), (x+w, y+h), (0, 0, 255), 2)
            
            # #enable only sending frames with face detection
            # if(len(faces) == 0):
            #     continue
            
            bSndMsg = True
            bWriteVideo = True
            result, framePacked = cv2.imencode('.jpg', frame, encode_param)

        if(bool(args.display) == True):
            cv2.imshow('img', frame)
            k = cv2.waitKey(30) & 0xff
            if k == 27:
                break
            elif k == ord('s'):     # simulate detection of HCSR04 sensor
                bDetected = not bDetected

        if(True == bMulticast and True == bSndMsg):
            serversock.sendto(framePacked, (MCAST_GRP, port))

    except KeyboardInterrupt:
        break

cap.release()
cv2.destroyAllWindows()

if(False == bMulticast):
    for client in clients:
        client.shutdown(socket.SHUT_RDWR)
        client.close()
    
bClientConnection = False
bDistanceDetection = False
bRecordVideo = False

try:
    serversock.shutdown(socket.SHUT_RDWR)
    serversock.close()
except OSError:
    serversock.close()

if(False == bMulticast):
    if(clients_lock.locked() == True):
        clients_lock.release()

for thd in th:
    thd.join()

print("\nSuccessfully closed server application\n")
exit() 
