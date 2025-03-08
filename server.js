require("dotenv").config();
const express = require("express");
const mongoose = require("mongoose");
const cors = require("cors");
const bodyParser = require("body-parser");
const cookieParser = require("cookie-parser");
const axios = require("axios");
const { google } = require("googleapis");

const app = express();
const port = process.env.PORT || 5000;

// Middleware
app.use(cors({
  origin: 'http://localhost:3000', // Allow React app origin
  credentials: true // Allow cookies to be sent
}));
app.use(bodyParser.json());
app.use(cookieParser());

// MongoDB Connection
mongoose.connect(process.env.MONGO_URI, {
  useNewUrlParser: true,
  useUnifiedTopology: true,
});

const db = mongoose.connection;
db.once("open", () => console.log("MongoDB Connected"));
db.on("error", (err) => console.error("MongoDB Connection Error:", err));

// OAuth2 Credentials from Google Developer Console
const CLIENT_ID = process.env.CLIENT_ID;
const CLIENT_SECRET = process.env.CLIENT_SECRET;
const REDIRECT_URI = "http://localhost:5000"; // Update this to match the new URI

console.log(CLIENT_ID);

if (!CLIENT_ID || !CLIENT_SECRET) {
  console.error("Error: Missing CLIENT_ID or CLIENT_SECRET in environment variables.");
  process.exit(1);  // Exit if credentials are missing
}

// Create OAuth2 client
const oauth2Client = new google.auth.OAuth2(CLIENT_ID, CLIENT_SECRET, REDIRECT_URI);

// Step 1: Redirect user to Google OAuth consent screen
app.get("/auth", (req, res) => {
  const authUrl = oauth2Client.generateAuthUrl({
    access_type: "offline",
    scope: ["https://www.googleapis.com/auth/fitness.activity.read"],
  });
  console.log("Redirecting to Google OAuth URL:", authUrl);  // Log the auth URL for debugging
  res.redirect(authUrl);
});

// Step 2: Handle OAuth2 callback, exchange code for tokens
app.get("/auth/callback", async (req, res) => {
  const code = req.query.code;
  if (!code) {
    return res.status(400).json({ error: "No authorization code received." });
  }

  console.log("Received code from Google OAuth:", code); // Log the received code

  try {
    const { tokens } = oauth2Client.getToken(code);
    oauth2Client.setCredentials(tokens); // Store the access token
    res.cookie("google_access_token", tokens.access_token, { httpOnly: true, secure: false }); // Store token in cookie
    console.log("OAuth2 token received and stored."); // Log successful token exchange
    res.redirect("/dashboard");
  } catch (error) {
    console.error("Error during token exchange:", error);
    res.status(500).json({ error: "Authentication failed" });
  }
});

// Step 3: Fetch data from Google Fit API (Calories Burned)
app.get("/get-calories-burned", async (req, res) => {
  const accessToken = req.cookies.google_access_token;
  if (!accessToken) {
    return res.status(401).json({ error: "Not authenticated" });
  }

  try {
    const response = await axios.post(
      "https://www.googleapis.com/fitness/v1/users/me/dataset:aggregate",
      {
        aggregateBy: [
          {
            dataTypeName: "com.google.calories.expended",
          },
        ],
        bucketByTime: { durationMillis: 86400000 }, // Daily
        startTimeMillis: Date.now() - 1000 * 60 * 60 * 24, // Last 24 hours
        endTimeMillis: Date.now(),
      },
      {
        headers: {
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
      }
    );

    const caloriesBurned =
      response.data.bucket?.[0]?.dataset?.[0]?.point?.[0]?.value?.[0]?.fpVal || 0;
    console.log("Calories burned:", caloriesBurned); // Log the calories burned
    res.json({ caloriesBurned });
  } catch (error) {
    console.error("Error fetching calories from Google Fit:", error);
    res.status(500).json({ error: "Failed to fetch calories burned data" });
  }
});

// Dashboard route
app.get("/dashboard", (req, res) => {
  res.send("Welcome to your dashboard!");
});

const WEATHER_API_KEY = "6e3dc4ef92f541ea827224944252802";

// Fetch weather data using latitude and longitude
app.post('/api/weather', async (req, res) => {
  const { lat, lon } = req.body;

  if (!lat || !lon) {
    return res.status(400).json({ error: 'Latitude and longitude are required' });
  }

  try {
    const response = await axios.get(
      `https://api.weatherapi.com/v1/current.json?key=${WEATHER_API_KEY}&q=${lat},${lon}`
    );
    
    const weatherData = response.data;
    
    // Send temperature data and weather condition to frontend
    res.json({
      temperature: weatherData.current.temp_c,
      condition: weatherData.current.condition.text,
      humidity: weatherData.current.humidity
    });
  } catch (error) {
    console.error('Error fetching weather data:', error);
    res.status(500).json({ error: 'Failed to fetch weather data' });
  }
});



// Import Routes for authentication and user data
const authRoutes = require("./Routes/authRoutes");
const userRoutes = require("./Routes/userRoutes");

app.use("/api/auth", authRoutes);
app.use("/api/users", userRoutes);

// Start the server
app.listen(port, () => console.log(`✅ Server running on port ${port}`));
