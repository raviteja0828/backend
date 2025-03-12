const express = require("express");
const jwt = require("jsonwebtoken");
const User = require("../models/user");

const router = express.Router();

// Middleware to verify token
const authenticate = (req, res, next) => {
  const authHeader = req.header("Authorization");
  if (!authHeader) {
    console.log("🚨 No token provided!");
    return res.status(401).json({ message: "Access denied. No token provided." });
  }

  const token = authHeader.split(" ")[1]; // Extract Bearer token
  if (!token) {
    console.log("🚨 Invalid Authorization header format!");
    return res.status(401).json({ message: "Invalid token format" });
  }

  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET);
    req.user = decoded;
    console.log("✅ Token Verified:", decoded);
    next();
  } catch (error) {
    console.error("🚨 Token Verification Failed:", error);
    res.status(400).json({ message: "Invalid token" });
  }
};

// @route   POST /api/users/save
router.post("/save", authenticate, async (req, res) => {
  try {
    console.log("📩 Received Data from Client:", req.body);

    const { gender, age, activity, height, weight, targetWeight, medicalCondition } = req.body;

    if (!gender || !age || !activity || !height || !weight || !targetWeight) {
      return res.status(400).json({ error: "Missing required fields" });
    }

    const bmi = (weight / ((height / 100) ** 2)).toFixed(1);
    const calorieIntake = (weight * (activity === "Sedentary" ? 24 : activity === "Moderate" ? 30 : 35)).toFixed(0);
    const macros = {
      protein: Math.round((calorieIntake * 0.3) / 4),
      carbs: Math.round((calorieIntake * 0.4) / 4),
      fats: Math.round((calorieIntake * 0.3) / 9),
      magnesium: 0.4,
      sodium: 1,
    };
    const estimatedTimeToTargetWeight = `${(Math.abs(weight - targetWeight) / 0.45).toFixed(1)} weeks`;

    const Intake = 0;

    // Save to database
    const user = await User.findByIdAndUpdate(req.user.userId, {
      gender,
      age,
      activity,
      height,
      weight,
      targetWeight,
      medicalCondition,
      bmi,
      calorieIntake,
      Intake,
      macros,
      estimatedTimeToTargetWeight,
    });

    if (!user) {
      return res.status(404).json({ message: "User not found" });
    }

    console.log("✅ Data saved successfully!");
    res.json({ message: "Health data saved successfully!" });
  } catch (error) {
    console.error("🚨 Server Error:", error);
    res.status(500).json({ error: "Server error while saving data" });
  }
});

router.get("/profile", authenticate, async (req, res) => {
  try {
    const user = await User.findById(req.user.userId).select(
      "name email gender age activity height weight targetWeight medicalCondition bmi calorieIntake Intake macros estimatedTimeToTargetWeight  measurements sleepData"
    );

    if (!user) {
      return res.status(404).json({ message: "User not found" });
    }

    console.log("✅ Sending User Profile:", user);
    res.json(user);
  } catch (error) {
    console.error("🚨 Server Error:", error);
    res.status(500).json({ error: "Server error fetching user data" });
  }
});
router.post("/update-measurements", authenticate, async (req, res) => {
  try {
      const user = await User.findById(req.user.userId);
      if (!user) {
          return res.status(404).json({ message: "User not found" });
      }

      const { chest, waist, hips } = req.body;

      user.measurements = {
          chest: chest !== undefined ? chest : user.measurements?.chest,
          waist: waist !== undefined ? waist : user.measurements?.waist,
          hips: hips !== undefined ? hips : user.measurements?.hips,
      };
      await user.save();
      
      // ✅ Return updated user data
      const updatedUser = await User.findById(req.user.userId);
      res.json({ message: "✅ Measurements updated successfully", user: updatedUser });

  } catch (error) {
      console.error(error);
      res.status(500).json({ message: "Server error" });
  }
});

router.post("/log-food", authenticate, async (req, res) => {
  try {
      const { name, calories, carbs, proteins, fats } = req.body;
      const userId = req.user.userId;
      const foodLog = { name, calories, carbs, proteins, fats, date: new Date() };

      // Update user's calorie intake
      const user = await User.findById(userId);
      if (!user) return res.status(404).json({ message: "User not found" });

      user.Intake += calories; // Update total intake
      await user.save();

      // Save food log
      await foodLog.create(foodLog);
      res.json({ message: "Food logged successfully!" });
  } catch (error) {
      res.status(500).json({ error: "Error logging food" });
  }
});

router.post("/sleep", authenticate, async (req, res) => {
  const { date, hours } = req.body;

  try {
    const user = await User.findById(req.user.userId);
    if (!user) {
      return res.status(404).json({ message: "User not found" });
    }

    // Check if sleep data for the given date already exists
    const existingSleepData = user.sleepData.find((data) => data.date === date);

    if (existingSleepData) {
      // Update existing sleep data
      existingSleepData.hours = hours;
    } else {
      // Add new sleep data
      user.sleepData.push({ date, hours });
    }

    await user.save();

    res.json({ message: "Sleep data saved/updated successfully" });
  } catch (error) {
    console.error("🚨 Error saving/updating sleep data:", error);
    res.status(500).json({ message: "Server error while saving/updating sleep data" });
  }
});

// Route to get sleep data for the user (last 7 days)
router.get("/sleep", authenticate, async (req, res) => {
  const today = new Date();
  const last7Days = [];

  // Generate last 7 days' dates
  for (let i = 6; i >= 0; i--) {
    const date = new Date(today);
    date.setDate(today.getDate() - i);
    last7Days.push(date.toLocaleDateString());
  }

  try {
    const user = await User.findById(req.user.userId);
    if (!user) {
      return res.status(404).json({ message: "User not found" });
    }

    const sleepData = user.sleepData.filter((data) =>
      last7Days.includes(data.date)
    );

    // If no data for some dates, default to 6 hours of sleep
    const sleepDataMap = sleepData.reduce((acc, curr) => {
      acc[curr.date] = curr.hours;
      return acc;
    }, {});

    const sleepHours = last7Days.map((day) => sleepDataMap[day] || 6); // Default 6 hours if no data

    res.json({ sleepHours, last7Days });
  } catch (error) {
    console.error("🚨 Error fetching sleep data:", error);
    res.status(500).json({ message: "Error fetching sleep data" });
  }
});

router.post("/update-health-data", authenticate, async (req, res) => {
  try {
    const { height, weight, age, activity, targetWeight } = req.body;

    if (!height || !weight || !age || !activity || !targetWeight) {
      return res.status(400).json({ error: "Missing required fields" });
    }

    // Calculate BMI
    const bmi = (weight / ((height / 100) ** 2)).toFixed(1);

    // Calculate Calorie Intake
    const calorieIntake = (weight * (activity === "Sedentary" ? 24 : activity === "Moderate" ? 30 : 35)).toFixed(0);

    // Calculate Macros
    const macros = {
      protein: Math.round((calorieIntake * 0.3) / 4),
      carbs: Math.round((calorieIntake * 0.4) / 4),
      fats: Math.round((calorieIntake * 0.3) / 9),
      magnesium: 0.4, // Placeholder value for magnesium
      sodium: 1, // Placeholder value for sodium
    };

    // Calculate Estimated Time to Target Weight (based on 0.45kg weight loss per week)
    const estimatedTimeToTargetWeight = `${(Math.abs(weight - targetWeight) / 0.45).toFixed(1)} weeks`;

    // Update the user's data in the database
    const user = await User.findByIdAndUpdate(req.user.userId, {
      height,
      weight,
      age,
      activity,
      targetWeight,
      bmi,
      calorieIntake,
      macros,
      estimatedTimeToTargetWeight,
    });

    if (!user) {
      return res.status(404).json({ message: "User not found" });
    }

    res.json({ message: "Health data updated successfully!" });
  } catch (error) {
    console.error("🚨 Error updating health data:", error);
    res.status(500).json({ error: "Server error while updating data" });
  }
});



module.exports = router;
