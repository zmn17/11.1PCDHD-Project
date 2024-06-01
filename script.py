import logging
import sys
import os
import time
import cv2
import face_recognition
import numpy as np
import paho.mqtt.client as mqtt
from picamera2 import Picamera2
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (QApplication, QLabel, QMainWindow, QVBoxLayout, QWidget)
from datetime import datetime

# List of authorized RFID tags
authorized_tags = ['43d0531b']

# Setup logging
logging.basicConfig(filename='informationLogs.log', level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        
        self.door_status = 'locked'

        self.setWindowTitle("Face Recognition and Video Surveillance")
        self.setGeometry(100, 100, 1280, 720)

        self.label = QLabel(self)
        self.label.resize(1280, 720)

        layout = QVBoxLayout()
        layout.addWidget(self.label)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.picam2 = Picamera2()
        self.picam2.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(100)

        self.known_face_encodings = []
        self.known_face_names = []

        # Load and encode faces from multiple images
        self.load_known_faces("./images")

        # Setup MQTT
        self.mqtt_client = mqtt.Client()
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message
        self.mqtt_client.connect("localhost", 1883, 60)
        self.mqtt_client.loop_start()

        # Setup video writer for surveillance recording
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        self.video_writer = cv2.VideoWriter('surveillance.mp4', fourcc, 10, (1280, 720))

        # Door state and cooldown period
        self.door_unlocked = False
        self.last_unlock_time = 0
        self.unlock_duration = 3  # stays unlocked for 3 secs

    def load_known_faces(self, base_dir):
        for person_name in os.listdir(base_dir):
            person_dir = os.path.join(base_dir, person_name)
            if not os.path.isdir(person_dir):
                continue
            for image_name in os.listdir(person_dir):
                image_path = os.path.join(person_dir, image_name)
                image = face_recognition.load_image_file(image_path)
                face_encodings = face_recognition.face_encodings(image)
                if face_encodings:
                    self.known_face_encodings.append(face_encodings[0])
                    self.known_face_names.append(person_name)
                    logging.info(f"Loaded encoding for {person_name} from {image_name}")

    def on_connect(self, client, userdata, flags, rc):
        client.subscribe("door/rfid")
        client.subscribe("door/face_recognition")

    def on_message(self, client, userdata, msg):
        if msg.topic == "door/rfid":
            self.handle_rfid(msg.payload)
        elif msg.topic == "door/face_recognition":
            self.handle_face_recognition(msg.payload)

    def handle_rfid(self, payload):
        rfid_tag = payload.decode()
        if rfid_tag in authorized_tags:
            self.door_status = 'unlock'
            self.mqtt_client.publish("door/lock", self.door_status)
            logging.info(f"RFID recognized: {rfid_tag} - Door Unlocked")
            QTimer.singleShot(3000, self.lock_door)  
        else:
            self.door_status = 'lock'
            self.mqtt_client.publish("door/lock", self.door_status)
            logging.info(f"Unauthorized RFID attempt: {rfid_tag} - Door Locked")

    def handle_face_recognition(self, payload):
        if payload.decode() == "recognized":
            self.door_status = 'unlock'
            self.mqtt_client.publish("door/lock", self.door_status)
            logging.info("Face recognized - Door Unlocked")
        else:
            self.door_status = 'lock'
            self.mqtt_client.publish("door/lock", self.door_status)
            logging.info("Face not recognized - Door Locked")

    def lock_door(self):
        self.door_status = 'lock'
        self.mqtt_client.publish("door/lock", self.door_status)
        logging.info("Door Locked after unlock duration")

    def update_frame(self):
        now = datetime.now()
        frame = self.picam2.capture_array()
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        # Save captures frame for inspection
        os.makedirs(f"{now.year}-{now.month}-{now.day}", exist_ok=True)
        cv2.imwrite(f"{now.year}-{now.month}-{now.day}/{now.hour}:{now.minute}:{now.second}--captured_image.jpg", frame)

        face_locations = face_recognition.face_locations(rgb_frame)
        face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)

        current_time = time.time()
        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
            matches = face_recognition.compare_faces(self.known_face_encodings, face_encoding)
            name = "Unknown"

            if True in matches:
                first_match_index = matches.index(True)
                name = self.known_face_names[first_match_index]

                if not self.door_unlocked:
                    self.door_unlocked = True
                    self.last_unlock_time = current_time
                    self.mqtt_client.publish("door/face_recognition", "recognized")
                    logging.info(f"Recognized: {name} - Door Unlocked")
                else:
                    logging.info("Unknown face detected")

            cv2.rectangle(frame, (left, top), (right, bottom), (0, 0, 255), 2)
            cv2.rectangle(frame, (left, bottom - 35), (right, bottom), (0, 0, 255), cv2.FILLED)
            font = cv2.FONT_HERSHEY_DUPLEX
            cv2.putText(frame, name, (left + 6, bottom - 6), font, 1.0, (255, 255, 255), 1)

        if self.door_unlocked and current_time - self.last_unlock_time > self.unlock_duration:
            self.door_unlocked = False
            self.mqtt_client.publish("door/face_recognition", "lock")
            logging.info("Door Locked after cooldown period")

        height, width, channel = frame.shape
        step = channel * width
        q_img = QImage(frame.data, width, height, step, QImage.Format_RGB888)
        self.label.setPixmap(QPixmap.fromImage(q_img))

    def closeEvent(self, event):
        self.picam2.stop()
        self.mqtt_client.loop_stop()
        self.mqtt_client.disconnect()
        self.video_writer.release()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    main_window = MainWindow()
    main_window.show()
    sys.exit(app.exec_())
