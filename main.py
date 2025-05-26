from flask import Flask, render_template, request, session, redirect, url_for
from flask_socketio import join_room, leave_room, send, SocketIO
from pymongo import MongoClient
from datetime import datetime
import re
from dotenv import load_dotenv
import os

def configure():
    load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = "abc"
socketio = SocketIO(app)

# MongoDB connection
cluster = MongoClient(f"{os.getenv('api_key')}")
db = cluster["ChatApp"]
collection = db["messages"]

rooms = {}

# Provjera telefonskog broja
def is_valid_phone(phone):  
    if not phone:
        return False
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    return cleaned.isdigit() and len(cleaned) >= 10

# Dobavi podatke poruka iz MongoDB
def get_room_messages(room_code):
    try:
        messages = list(collection.find({"room": room_code}).sort("timestamp", 1))
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "name": msg["name"],
                "message": msg["message"],
                "timestamp": msg["timestamp"].strftime("%H:%M")
            })
        return formatted_messages
    except Exception as e:
        print(f"Error retrieving messages: {e}")
        return []

# Spremi poruku u MongoDB
def save_message_to_db(room_code, name, message):
    try:
        message_doc = {
            "room": room_code,
            "name": name,
            "message": message,
            "timestamp": datetime.now()
        }
        collection.insert_one(message_doc)
    except Exception as e:
        print(f"Error saving message: {e}")

@app.route("/", methods=["GET", "POST"])
def home():
    session.clear()
    if request.method == "POST":
        name = request.form.get("name")
        phone = request.form.get("phone")
        join_phone = request.form.get("join_phone")
        join = request.form.get("join", False)
        create = request.form.get("create", False)

        if not name:
            return render_template("home.html", error="Please enter a name.", phone=phone, join_phone=join_phone, name=name)
        
        if not phone:
            return render_template("home.html", error="Please enter your phone number.", phone=phone, join_phone=join_phone, name=name)
        
        if not is_valid_phone(phone):
            return render_template("home.html", error="Please enter a valid phone number.", phone=phone, join_phone=join_phone, name=name)

        if create != False:
            # Create room - telefonski broj je room code
            room_code = phone.strip()
            if room_code not in rooms:
                rooms[room_code] = {"members": 0, "messages": []}
        elif join != False:
            # Join room - potreban je room code
            if not join_phone:
                return render_template("home.html", error="Please enter a phone number to join.", phone=phone, join_phone=join_phone, name=name)
            
            if not is_valid_phone(join_phone):
                return render_template("home.html", error="Please enter a valid phone number to join.", phone=phone, join_phone=join_phone, name=name)
            
            room_code = join_phone.strip()
            # Check if room exists (has messages in DB or is currently active)
            existing_messages = get_room_messages(room_code)
            if room_code not in rooms and not existing_messages:
                return render_template("home.html", error="Room does not exist.", phone=phone, join_phone=join_phone, name=name)
            if room_code not in rooms:
                rooms[room_code] = {"members": 0, "messages": []}

        session["room"] = room_code
        session["name"] = name
        session["user_phone"] = phone  # Store user's own phone number
        return redirect(url_for("room"))

    return render_template("home.html")

@app.route("/room")
def room():
    room = session.get("room")
    if room is None or session.get("name") is None:
        return redirect(url_for("home"))
    
    # Ako soba ne postoji, inicijaliziraj je
    if room not in rooms:
        rooms[room] = {"members": 0, "messages": []}
    
    # Dobavi poruke iz MongoDB
    messages = get_room_messages(room)
    
    return render_template("room.html", code=room, messages=messages)

@socketio.on("message")
def message(data):
    room = session.get("room")
    name = session.get("name")
    
    if not room or not name:
        return
    
    if room not in rooms:
        rooms[room] = {"members": 0, "messages": []}
    
    message_text = data["data"]
    timestamp = datetime.now()
    
    content = {
        "name": name,
        "message": message_text,
        "timestamp": timestamp.strftime("%H:%M")
    }
    
    # Spremi na MongoDB
    save_message_to_db(room, name, message_text)
    
    send(content, to=room)
    
    print(f"{name} said: {message_text}")

@socketio.on("connect")
def connect(auth):
    room = session.get("room")
    name = session.get("name")
    
    if not room or not name:
        return
    
    if room not in rooms:
        rooms[room] = {"members": 0, "messages": []}
    
    join_room(room)
    
    # Join notification
    join_content = {
        "name": name, 
        "message": "has joined the room.",
        "timestamp": datetime.now().strftime("%H:%M"),
        "is_notification": True
    }
    send(join_content, to=room)
    
    rooms[room]["members"] += 1
    print(f"{name} has joined room {room}.")

@socketio.on("disconnect")
def disconnect():
    room = session.get("room")
    name = session.get("name")
    
    if not room or not name:
        return
    
    leave_room(room)

    if room in rooms:
        rooms[room]["members"] -= 1
        if rooms[room]["members"] <= 0:
            del rooms[room]
    
    # Leave notification
    leave_content = {
        "name": name, 
        "message": "has left the room.",
        "timestamp": datetime.now().strftime("%H:%M"),
        "is_notification": True
    }
    send(leave_content, to=room)
    
    print(f"{name} has left room {room}.")

if __name__ == "__main__":
    configure()
    socketio.run(app, debug=True)