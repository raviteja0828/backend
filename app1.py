from flask import Flask, request, jsonify
import requests
import pymongo
import re
from flask_cors import CORS
import jwt  # For JWT token handling
from functools import wraps
from datetime import datetime
import tensorflow as tf
import pandas as pd
import numpy as np
import cv2
from PIL import Image
import io
import joblib
import os
import base64

app = Flask(__name__)

# Enable CORS to allow requests from React (running on port 3000)


CORS(app, resources={r"/*": {"origins": "*"}})


# MongoDB connection
client = pymongo.MongoClient("mongodb+srv://merakanapalliraviteja86:wejhTlHwGGgPMXbn@cluster0.q7okber.mongodb.net/ashu?retryWrites=true&w=majority")
db = client["ashu"]  # Ensure you're connecting to the 'ashu' database
user_food_data = db["user_food_data"]  # The collection where food data will be stored

# JWT Secret Key for Authentication
JWT_SECRET = 'your#super#secret#key'

portion_url = "https://ashu2807.s3.eu-north-1.amazonaws.com/portion_independent.h5"

# Folder to save downloaded files locally
DOWNLOAD_FOLDER = 'ml_model/'

# Ensure the download folder exists
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# Download the file from the provided URL
def download_file(url, destination):
    try:
        # Make an HTTP request to get the file
        response = requests.get(url)
        if response.status_code == 200:
            # Save the content to a file
            with open(destination, "wb") as file:
                file.write(response.content)
            print(f"File downloaded successfully to {destination}")
        else:
            print(f"Failed to download file. HTTP Status Code: {response.status_code}")
    except Exception as e:
        print(f"Error downloading file: {e}")

# File paths for the downloaded models

portion_file_path = os.path.join(DOWNLOAD_FOLDER, "portion_independent.h5")



if not os.path.exists(portion_file_path):
    download_file(portion_url, portion_file_path)

# Load the models after they are downloaded
if  os.path.exists(portion_file_path):
    portion_independent = tf.keras.models.load_model(portion_file_path)
    print("Model loaded successfully.")
else:
    print(f"files are missing.")


classes = pd.read_json('ml_models/class_encoding.json')
class_map = dict(zip(classes['idx'], classes['ingr']))

def authenticate(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token is missing!'}), 403
        try:
            data = jwt.decode(token.split(" ")[1], JWT_SECRET, algorithms=["HS256"])
            current_user_id = data['userId']
            request.user_id = current_user_id  # Storing user_id to request object
        except jwt.ExpiredSignatureError:
            return jsonify({'message': 'Token has expired!'}), 403
        except jwt.InvalidTokenError:
            return jsonify({'message': 'Invalid token!'}), 403
        return f(*args, **kwargs)
    return decorated_function

def get_today_date():
    return datetime.now().strftime('%Y-%m-%d') 

def calories_from_macro(protein, carbs, fat):
    return protein * 4 + carbs * 4 + fat * 9

def make_portion_independent_prediction(img, model, total_mass):
    predictions = model.predict(img)
    print(total_mass)
    total_mass=int(total_mass)

    # Make sure predictions are extracted correctly, assuming it returns a dict-like object.
    protein = predictions['protein'][0][0] * total_mass  # Ensure correct indexing
    fat = predictions['fat'][0][0] * total_mass          # Ensure correct indexing
    carbs = predictions['carbs'][0][0] * total_mass      # Ensure correct indexing
    
    calories = protein * 4 + carbs * 4 + fat * 9  # Calculate calories based on macros
    
    return {
        'protein': protein,
        'fat': fat,
        'carbs': carbs,
        'calories': calories,
        'mass': total_mass
    }

@app.route('/predict', methods=['POST'])
@authenticate
def predict():
    data = request.json
    image_data = data.get('image')  # Get base64 string
    meal_type = data.get('meal_type', 'breakfast') 
    mass = data.get('mass')  # Default mass value is 100 if not provided
    print(f"Received mass: {mass}")  # Debug print for mass
    token = request.headers.get('Authorization')
    user_id = request.user_id 
    today = get_today_date()
    
    if not image_data:
        return jsonify({"error": "No image data provided"}), 400
    
    try:
        # Decode the base64 string to bytes
        print(f"Received image data: {image_data[:100]}...") 
        image_data = image_data.split(',')[1] if 'base64' in image_data else image_data
        image_bytes = base64.b64decode(image_data)  # Decode base64 image
        img = Image.open(io.BytesIO(image_bytes)).convert('RGB') # Open image from bytes


        # Resize image to (320, 320) as expected by the model
        img_resized = img.resize((320, 320))

        # Convert the image to a numpy array and normalize if necessary
        img_array = np.array(img_resized)
        img_array = np.expand_dims(img_array, axis=0)# Add batch dimension
        print(f"Image array shape: {img_array.shape}")


        prediction = make_portion_independent_prediction(img_array, portion_independent, mass)  # Pass actual model
        nutrition = prediction

         # User ID from JWT token

        save_data = {
            "user_id": user_id, 
            "calories": nutrition['calories'],
            "carbs": nutrition['carbs'],
            "proteins": nutrition['protein'],
            "fats": nutrition['fat'],
            "date": datetime.today(),
            "meal_type": meal_type
        }

        # Save to database
        user_food_data.insert_one(save_data)
        daily_record = db["user_daily_calories"].find_one({"user_id": user_id, "date": today})
        
        if daily_record:
            # Update daily calorie intake for the current date
            db["user_daily_calories"].update_one(
                {"user_id": user_id, "date": today},
                {"$inc": {"total_calories": nutrition['calories']}},
            )
        else:
            # Create a new record for today's calories
            db["user_daily_calories"].insert_one({
                "user_id": user_id,
                "date": today,
                "total_calories":nutrition['calories']
            })


        # Combine the results from both predictions and send back in the response
        return jsonify({
            'nutrition': prediction
        })
    except Exception as e:
        print("Error processing image:", e)
        return jsonify({"error": "Failed to process image."}), 500

if __name__ == '__main__':
    app.run( port=5002,debug=True)
