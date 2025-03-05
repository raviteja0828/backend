const mongoose = require("mongoose");

const UserSchema = new mongoose.Schema({
  name: { type: String, required: true },
  email: { type: String, required: true, unique: true },
  password: { type: String, required: true },
  gender: { type: String },
  age: { type: Number },
  activity: { type: String },
  height: { type: Number },
  weight: { type: Number },
  targetWeight: { type: Number },
  medicalCondition: { type: [String] },
  bmi: { type: Number },
  calorieIntake: { type: Number },
  Intake:{type: Number},
  macros: {
    protein: { type: Number },
    carbs: { type: Number },
    fats: { type: Number },
    magnesium: { type: Number },
    sodium: { type: Number },
  },
  estimatedTimeToTargetWeight: { type: String },

  // ✅ New Measurements Section
  measurements: {
    chest: { type: Number, default: null },
    waist: { type: Number, default: null },
    hips: { type: Number, default: null },
  },
  sleepData: [
    {
      date: { type: String, required: true },
      hours: { type: Number, required: true },
    },
  ],
});

module.exports = mongoose.model("User", UserSchema);
