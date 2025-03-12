from flask import Flask, request, jsonify
import requests
import pymongo
import re
from flask_cors import CORS
import jwt  # For JWT token handling
from functools import wraps
from datetime import datetime
import pytz



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
    today = get_today_date()
    
    if data:
        # Save food data into the unified collection: user_food_data
        save_data = {
            "user_id": user_id,  # Associate food intake with the user
            "food_name": data.get("name"),
            "calories": data.get("calories", 0),
            "carbs": data.get("carbs", 0),
            "proteins": data.get("proteins", 0),
            "fats": data.get("fats", 0),
            "date": today,
            "meal_type": data.get("mealType", "breakfast")
        }

        # Insert into the unified collection
        user_food_data.insert_one(save_data)

        # Get today's date to track daily calorie count
       

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

def get_today_date():
    # Use local timezone to ensure the correct date
    local_timezone = pytz.timezone("Asia/Kolkata")  # Replace with your local timezone if different
    today = datetime.now(local_timezone)
    return today.strftime('%Y-%m-%d') 


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
@app.route('/data', methods=['GET'])
@authenticate
def data():
    today = get_today_date()
    print(today)  # Get today's date in YYYY-MM-DD format
    
    try:
        user_id = request.user_id  # Extracting user_id from the authenticated request
        print(f"Today: {today}, User ID: {user_id}")
        
        # MongoDB Aggregation Pipeline to get the total macros for today's food logs
        pipeline = [
            {"$match": {"user_id": user_id, "date": {"$gte": today}}},
            {"$group": {
                "_id": None,
                "totalCalories": {"$sum": "$calories"},
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
                "totalCalories": 0,
                "totalCarbs": 0,
                "totalProteins": 0,
                "totalFats": 0,
            }), 200
        
        # Extract data from the aggregation result
        data = result[0]
        return jsonify({
            "totalCalories": data['totalCalories'],
            "totalCarbs": data['totalCarbs'],
            "totalProteins": data['totalProteins'],
            "totalFats": data['totalFats'],
        }), 200

    except Exception as e:
        print("Error fetching breakfast data:", e)
        return jsonify({"error": "Could not retrieve data."}), 500
    

from flask import Flask, jsonify, request
from datetime import datetime
from bson import ObjectId

# Assuming user_food_data is your collection and authenticate is your decorator
@app.route('/total-macros', methods=['GET'])
@authenticate
def get_total_macros():
    start_date = request.args.get('startDate')
    end_date = request.args.get('endDate')

    try:
        user_id = request.user_id  # Extracting user_id from the authenticated request

        # Format the dates to match the database format
        start_date = datetime.strptime(start_date, "%Y-%m-%d")
        end_date = datetime.strptime(end_date, "%Y-%m-%d")

        # Aggregate data for each day, grouped by meal type and date
        pipeline = [
            {"$match": {"user_id": user_id, "date": {"$gte": start_date, "$lte": end_date}}},
            {"$group": {
                "_id": {"meal_type": "$meal_type", "date": "$date"},
                "foods": {"$push": {
                    "food_name": "$food_name",
                    "calories": "$calories",
                    "carbs": "$carbs",
                    "proteins": "$proteins",
                    "fats": "$fats"
                }}
            }},
            {"$sort": {"_id.date": 1}}  # Sort by date to make the data chronological
        ]

        result = list(user_food_data.aggregate(pipeline))
        print(result)

        if not result:
            return jsonify({"message": "No data found for the selected date range"}), 200

        # Return the formatted data
        data = []
        for item in result:
            data.append({
                "date": item["_id"]["date"].strftime("%Y-%m-%d"),  # Format date to string
                "meal_type": item["_id"]["meal_type"],
                "foods": item["foods"]
            })

        return jsonify(data), 200

    except Exception as e:
        print("Error fetching macros data:", e)
        return jsonify({"error": "Could not retrieve data."}), 500


    

  # Ensure this port matches your fro
    
if __name__ == '__main__':
    app.run(host='0.0.0.0',debug=False, port=5000)  # Ensure this port matches your frontend calls
