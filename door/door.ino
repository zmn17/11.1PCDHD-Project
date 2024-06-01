#include <SPI.h>
#include <MFRC522.h>
#include <WiFiNINA.h>
#include <PubSubClient.h>
#include <Servo.h>
#include <U8g2lib.h>

// Define pins for the RFID reader
#define SS_PIN 16
#define RST_PIN 17
MFRC522 rfid(SS_PIN, RST_PIN);

// Define pins for the door lock servo and buzzer
Servo doorLock;
const int buzzer = 5;

// WiFi credentials
char ssid[] = "Not-Connected...";
char pass[] = "ZH9FagdbAdXMNpk3";
int status = WL_IDLE_STATUS;

// MQTT server
const char* mqtt_server = "192.168.1.199";
WiFiClient wifiClient;
PubSubClient client(wifiClient);

// Initialize the display using the U8g2 constructor
U8G2_SH1106_128X64_NONAME_F_4W_HW_SPI u8g2(U8G2_R0, /* cs=*/ 10, /* dc=*/ 9, /* reset=*/ 6);
void setup() {
  // Initialize serial communication
  Serial.begin(9600);
  
  // Attempt to connect to WiFi network
  while (status != WL_CONNECTED) {
    Serial.print("Attempting to connect to WPA SSID: ");
    Serial.println(ssid);
    status = WiFi.begin(ssid, pass);
    delay(10000);
  }

  // Initialize SPI and RFID
  SPI.begin();
  rfid.PCD_Init();
  
  // Initialize the servo and buzzer
  doorLock.attach(3);
  pinMode(buzzer, OUTPUT);
  
  // Setup MQTT
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);

  // Initialize the OLED display
  u8g2.begin();
  displayMessage("System ready...");
  delay(1000);
  displayMessage("Scan your face or\nuser your RFID key...");
}

void loop() {
  // Ensure the client is connected to the MQTT broker
  if (!client.connected()) {
    reconnect();
  }
  client.loop();

  // Check for new RFID cards
  if (!rfid.PICC_IsNewCardPresent()) {
    return;
  }

  if (!rfid.PICC_ReadCardSerial()) {
    return;
  }

  // Read the RFID tag and convert it to a string
  String rfidTag = "";
  for (byte i = 0; i < rfid.uid.size; i++) {
    rfidTag += String(rfid.uid.uidByte[i], HEX);
  }
  Serial.println(rfidTag);

  // Publish the RFID tag to the MQTT topic
  client.publish("door/rfid", rfidTag.c_str());

  // Display RFID scanning status
  displayMessage("Scanning RFID...");
  delay(2000);
}

void callback(char* topic, byte* payload, unsigned int length) {
  // Convert the payload to a string
  String message;
  for (int i = 0; i < length; i++) {
    message += (char)payload[i];
  }

  // Handle messages for door lock and face recognition
  if (String(topic) == "door/lock") {
    if (message == "unlock") {
      doorLock.write(0);
      tone(buzzer, 1000, 500);
      displayMessage("Door Unlocked");

      // Schedule door to lock after 5 seconds
      delay(5000);
      lockDoor();
    } else if (message == "lock") {
      lockDoor();
    }
  } else if (String(topic) == "door/face_recognition") {
    displayMessage("Face Recognition...");
    delay(2000);
    if (message == "recognized") {
      client.publish("door/lock", "unlock");
      displayMessage("Face Recognized\nDoor Unlocked");
    } else if (message == "unknown") {
      client.publish("door/lock", "lock");
      displayMessage("Face Not Recognized\nDoor Locked");
    }
  }
}

void reconnect() {
  // Reconnect to the MQTT broker
  while (!client.connected()) {
    if (client.connect("ArduinoClient")) {
      client.subscribe("door/lock");
      client.subscribe("door/face_recognition");
    } else {
      delay(5000);
    }
  }
}

void lockDoor() {
  doorLock.write(90);
  tone(buzzer, 500, 500);
  displayMessage("Door Locked");
}

void displayMessage(String message) {
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_ncenB08_tr);

  // Split the message by newline character
  int y = 10;
  char buffer[128];
  message.toCharArray(buffer, 128);
  char* line = strtok(buffer, "\n");
  while (line != NULL) {
    int16_t x = (u8g2.getDisplayWidth() - u8g2.getStrWidth(line)) / 2;
    u8g2.drawStr(x, y, line);
    y += 12; // Move to the next line, adjust as needed
    line = strtok(NULL, "\n");
  }

  u8g2.sendBuffer();
}
