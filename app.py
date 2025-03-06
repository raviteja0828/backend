import os
import boto3
import tensorflow as tf
from botocore.exceptions import NoCredentialsError
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
import base64
import os


s3_client = boto3.client('s3',
                         aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                         aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                         region_name=os.getenv('AWS_DEFAULT_REGION'))  # Replace with your region, e.g., 'us-east-1'

BUCKET_NAME = 'ashu2807'  # Replace with your S3 bucket name

# Folder where you want to download the file locally
DOWNLOAD_FOLDER = 'ml_model/'

# Ensure the download folder exists
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

def download_file_from_s3(file_key, destination):
    try:
        # Check if the file already exists
        if not os.path.exists(destination):
            # Download the file from S3 if it doesn't exist
            s3_client.download_file(BUCKET_NAME, file_key, destination)
            print(f"File '{file_key}' downloaded successfully to {destination}")
        else:
            print(f"File '{file_key}' already exists at {destination}. Skipping download.")
    except NoCredentialsError:
        print("Credentials not available.")
    except Exception as e:
        print(f"Error: {e}")

# Correct S3 keys (since the files are in the root of the bucket)
file_key_model = "model.h5"  # Correct key for the model file
file_key_portion = "portion_independent.h5"  # Correct key for the portion file

# Define the local paths where the files will be saved
model_file_path = os.path.join(DOWNLOAD_FOLDER, "model.h5")
portion_file_path = os.path.join(DOWNLOAD_FOLDER, "portion_independent.h5")

# Download the files only if they don't exist locally
download_file_from_s3(file_key_model, model_file_path)
download_file_from_s3(file_key_portion, portion_file_path)

# Now load the models after they've been downloaded
if os.path.exists(portion_file_path) and os.path.exists(model_file_path):
    portion_independent = tf.keras.models.load_model(portion_file_path)
    image_model = tf.keras.models.load_model(model_file_path)
    print("Models loaded successfully.")
else:
    print(f"Error: One or both files are missing at: {portion_file_path} or {model_file_path}")


app = Flask(__name__)

# Enable CORS to allow requests from React (running on port 3000)
CORS(app, resources={r"/*": {"origins": "*"}})

# MongoDB connection
client = pymongo.MongoClient("mongodb+srv://merakanapalliraviteja86:wejhTlHwGGgPMXbn@cluster0.q7okber.mongodb.net/ashu?retryWrites=true&w=majority")
db = client["ashu"]  # Ensure you're connecting to the 'ashu' database
user_food_data = db["user_food_data"]  # The collection where food data will be stored

# JWT Secret Key for Authentication
JWT_SECRET = 'your#super#secret#key'

# USDA API Key
USDA_API_KEY = "ZFUU0bgFxh8cavVLZx7a1CKo5eTD15lvlpXxAaNV"
SEARCH_URL = f"https://api.nal.usda.gov/fdc/v1/foods/search?api_key={USDA_API_KEY}"
DETAIL_URL = f"https://api.nal.usda.gov/fdc/v1/food/{{}}?api_key={USDA_API_KEY}"








classes = pd.read_json('ml_models/class_encoding.json')
class_map = dict(zip(classes['idx'], classes['ingr']))


# Middleware to check for authentication
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

# Extract food and quantity from the search query (e.g., "100g apple")
def extract_food_and_quantity(query):
    match = re.search(r"(\d+)?\s*(g|gm|grams|mg|kg)?\s*(.*)", query, re.IGNORECASE)
    if match:
        quantity = int(match.group(1)) if match.group(1) else 100  # Default to 100g
        food_name = match.group(3).strip()
    else:
        quantity = 100  # Default to 100g if no quantity is given
        food_name = query.strip()
    return food_name, quantity

# Search for food products from the USDA database
@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('query', '')
    food_name, _ = extract_food_and_quantity(query)

    params = {'query': food_name, 'pageSize': 10}
    response = requests.get(SEARCH_URL, params=params)
    
    data = response.json()
    
    if 'foods' not in data:
        return jsonify({'error': 'Invalid API response'}), 500

    products = [
        {'code': str(p.get('fdcId', 'N/A')), 'name': p.get('description', 'Unknown')}
        for p in data.get('foods', [])
    ]
    return jsonify(products)

# Get details of a specific product by its code
@app.route('/product/<code>', methods=['GET'])
def get_product(code):
    response = requests.get(DETAIL_URL.format(code))
    data = response.json()

    if 'description' not in data:
        return jsonify({'error': 'Product not found'}), 404

    nutrients = {}
    if 'foodNutrients' in data:
        for nutrient in data['foodNutrients']:
            nutrient_name = nutrient.get('nutrient', {}).get('name', '')
            nutrient_value = nutrient.get('amount', 0)
            if nutrient_name:
                nutrients[nutrient_name] = nutrient_value

    product_data = {
        'code': code,
        'name': data.get('description', 'Unknown'),
        'calories': nutrients.get('Energy', 0),
        'carbs': nutrients.get('Carbohydrate, by difference', 0),
        'proteins': nutrients.get('Protein', 0),
        'fats': nutrients.get('Total lipid (fat)', 0),
    }
    return jsonify(product_data)

# Save food intake data into the new unified collection
@app.route('/save', methods=['POST'])
@authenticate
def save():
    data = request.json
    user_id = request.user_id  # Get the user ID from the authenticated request
    
    if data:
        # Save food data into the unified collection: user_food_data
        save_data = {
            "user_id": user_id,  # Associate food intake with the user
            "food_name": data.get("name"),
            "calories": data.get("calories", 0),
            "carbs": data.get("carbs", 0),
            "proteins": data.get("proteins", 0),
            "fats": data.get("fats", 0),
            "date": datetime.today(),
            "meal_type": data.get("mealType", "breakfast")
        }

        # Insert into the unified collection
        user_food_data.insert_one(save_data)

        # Get today's date to track daily calorie count
        today = get_today_date()

        # Check if there's already a record for the current day
        daily_record = db["user_daily_calories"].find_one({"user_id": user_id, "date": today})
        
        if daily_record:
            # Update daily calorie intake for the current date
            db["user_daily_calories"].update_one(
                {"user_id": user_id, "date": today},
                {"$inc": {"total_calories": data.get("calories", 0)}},
            )
        else:
            # Create a new record for today's calories
            db["user_daily_calories"].insert_one({
                "user_id": user_id,
                "date": today,
                "total_calories": data.get("calories", 0)
            })

        return jsonify({'message': 'Saved successfully', 'clear_input': True}), 201
    return jsonify({'error': 'No data provided'}), 400

# Get total calorie intake for the user
@app.route('/user-calories', methods=['GET'])
@authenticate
def get_user_calories():
    user_id = request.user_id  # Get the user ID from the authenticated request
    today = get_today_date()

    # Get today's calorie data
    daily_record = db["user_daily_calories"].find_one({"user_id": user_id, "date": today})

    if daily_record:
        return jsonify({'totalCalories': daily_record['total_calories']})
    
    # If no data for today, return 0 calories
    return jsonify({'totalCalories': 0})

# Get today's date
def get_today_date():
    return datetime.now().strftime('%Y-%m-%d')  # Format as 'YYYY-MM-DD'

# API endpoint to get the total breakfast calories for today
@app.route('/total-breakfast-calories', methods=['GET'])
@authenticate
def get_total_breakfast_calories():
    today = get_today_date()
    start_of_today = datetime.strptime(today, '%Y-%m-%d')
    meal_type = request.args.get('mealType', 'breakfast') 
    
    try:
        user_id = request.user_id  # Extracting user_id from the authenticated request
        
        # Sum the calories for the logged breakfast meals for today
        pipeline = [
            {"$match": {"user_id": user_id, "meal_type": meal_type, "date": {"$gte": start_of_today}}},
            {"$group": {
                "_id": None,
                "totalBreakfastCalories": {"$sum": "$calories"},
                "totalCarbs": {"$sum": "$carbs"},
                "totalProteins": {"$sum": "$proteins"},
                "totalFats": {"$sum": "$fats"},
            }}
        ]
        
        # Aggregate the data for the current day
        result = list(user_food_data.aggregate(pipeline))
        
        # If there's no data for today, return 0s
        if not result:
            return jsonify({
                "totalBreakfastCalories": 0,
                "totalCarbs": 0,
                "totalProteins": 0,
                "totalFats": 0,
            }), 200
        
        # Extract data from the aggregation result
        data = result[0]
        return jsonify({
            "totalBreakfastCalories": data['totalBreakfastCalories'],
            "totalCarbs": data['totalCarbs'],
            "totalProteins": data['totalProteins'],
            "totalFats": data['totalFats'],
        }), 200

    except Exception as e:
        print("Error fetching breakfast data:", e)
        return jsonify({"error": "Could not retrieve breakfast data."}), 500
    
def calories_from_macro(protein, carbs, fat):
    return protein * 4 + carbs * 4 + fat * 9

def make_image_prediction(img, model):
    predictions = model.predict(img)[0]
    indices = np.argsort(predictions)[::-1][:5]
    probs = [predictions[i] for i in indices]
    predicted_labels = [class_map[i] for i in indices]
    return predicted_labels, probs

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

        # Make predictions using the image model for ingredient prediction
        predictions, probabilities = make_image_prediction(img_array, image_model)  # Pass actual model
        predictions = [str(pred) for pred in predictions]  # Ensure all predictions are strings
        probabilities = [float(prob) for prob in probabilities]  # Convert to regular float

        # Now predict nutrition using the portion-independent model
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
            'ingredients': predictions,
            'probabilities': probabilities,
            'nutrition': prediction
        })
    
    except Exception as e:
        print("Error processing image:", e)
        return jsonify({"error": "Failed to process image."}), 500

  # Ensure this port matches your frontend calls
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001,debug=False)
