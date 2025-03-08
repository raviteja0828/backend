const express = require("express");
const bcrypt = require("bcryptjs");
const jwt = require("jsonwebtoken");
const nodemailer = require("nodemailer");
const User = require("models/user");
const OTP = require("models/otp"); // Import the OTP model
const rateLimit = require("express-rate-limit"); // For rate limiting
require("dotenv").config(); // Ensure .env variables are loaded

const router = express.Router();

// SMTP Configuration for Gmail
const transporter = nodemailer.createTransport({
  service: 'gmail',
  auth: {
    user: process.env.EMAIL_HOST_USER,  // 'merakanapalliraviteja86@gmail.com'
    pass: process.env.EMAIL_HOST_PASSWORD,  // 'csqo trhx xnat fmnz'
  },
});

// Rate limiting for OTP requests (e.g., 5 requests per minute)
const otpLimiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute
  max: 5, // limit to 5 requests per minute
  message: "Too many OTP requests, please try again after a minute",
});

// @route   POST /api/auth/signup
// @desc    Register a new user with OTP verification
router.post("/signup", async (req, res) => {
  const { name, email, password, otp } = req.body;

  // Validate required fields
  if (!name || !email || !password || !otp) {
    return res.status(400).json({ message: "All fields are required" });
  }

  // Verify OTP
  const storedOtp = await OTP.findOne({ email, otp });
  if (!storedOtp) {
    return res.status(400).json({ message: "Invalid or expired OTP" });
  }

  try {
    let user = await User.findOne({ email });
    if (user) return res.status(400).json({ message: "User already exists" });

    const hashedPassword = await bcrypt.hash(password, 10);
    user = new User({ name, email, password: hashedPassword });

    await user.save();

    // Generate a JWT Token
    const token = jwt.sign({ userId: user._id }, process.env.JWT_SECRET, { expiresIn: "7d" });

    res.status(201).json({
      message: "User registered successfully!",
      token,
      userId: user._id,
    });

    // Remove OTP from store after successful registration
    await OTP.deleteOne({ email });

  } catch (error) {
    console.error("Signup Error:", error);
    res.status(500).json({ error: "Internal Server Error" });
  }
});

// @route   POST /api/auth/send-otp
// @desc    Send OTP to the user's email with rate limiting
router.post("/send-otp", otpLimiter, async (req, res) => {
  const { email } = req.body;

  // Generate a random OTP
  const otp = Math.floor(100000 + Math.random() * 900000);

  // Save OTP in the database (with expiration time of 10 minutes)
  const newOtp = new OTP({ email, otp });
  await newOtp.save();

  // Send OTP email
  const mailOptions = {
    from: process.env.EMAIL_HOST_USER, // Sender's email
    to: email,                        // Recipient's email (user's email)
    subject: "Your OTP Code",
    text: `Your OTP code is: ${otp}`,
  };

  try {
    await transporter.sendMail(mailOptions);
    res.status(200).json({ message: "OTP sent successfully to your email." });
  } catch (err) {
    console.error("Error sending OTP:", err);
    res.status(500).json({ message: "Error sending OTP. Please try again." });
  }
});

// @route   POST /api/auth/verify-otp
// @desc    Verify OTP entered by the user
router.post("/verify-otp", async (req, res) => {
  const { email, otp } = req.body;

  // Check if the email and OTP exist in the database
  const storedOtp = await OTP.findOne({ email, otp });
  if (!storedOtp) {
    return res.status(400).json({ message: "Invalid or expired OTP" });
  }

  // OTP is valid
  res.status(200).json({ message: "OTP verified successfully." });
});

// @route   POST /api/auth/login
// @desc    Authenticate user & return token
router.post("/login", async (req, res) => {
  const { email, password } = req.body;

  // Validate required fields
  if (!email || !password) {
    return res.status(400).json({ message: "Email and password are required" });
  }

  try {
    const user = await User.findOne({ email });
    if (!user) return res.status(401).json({ message: "Invalid email or password" });

    const isMatch = await bcrypt.compare(password, user.password);
    if (!isMatch) return res.status(401).json({ message: "Invalid email or password" });

    // Generate a JWT Token
    const token = jwt.sign({ userId: user._id }, process.env.JWT_SECRET, { expiresIn: "7d" });

    res.json({
      message: "Login successful",
      token,
      userId: user._id,
      name: user.name,
      email: user.email,
    });
  } catch (error) {
    console.error("Login Error:", error);
    res.status(500).json({ error: "Internal Server Error" });
  }
});

// @route   POST /api/auth/forgot-password
// @desc    Send a reset password link to the user's email
router.post("/forgot-password", async (req, res) => {
  const { email } = req.body;

  // Find the user
  const user = await User.findOne({ email });
  if (!user) {
    return res.status(400).json({ message: "User not found" });
  }

  // Create a reset token (JWT or random token)
  const resetToken = jwt.sign({ userId: user._id }, process.env.JWT_SECRET, { expiresIn: '7d' });

  // Create the reset password link
  const resetLink = `http://localhost:3000/reset-password/${resetToken}`;

  // Send reset email
  const mailOptions = {
    from: process.env.EMAIL_HOST_USER, 
    to: email,
    subject: "Password Reset Request",
    text: `Click here to reset your password: ${resetLink}`,
  };

  try {
    await transporter.sendMail(mailOptions);
    res.status(200).json({ message: "Reset password link sent to your email." });
  } catch (err) {
    console.error("Error sending reset link:", err);
    res.status(500).json({ message: "Failed to send reset link. Please try again." });
  }
});

// @route   POST /api/auth/reset-password
// @desc    Reset password for the user
router.post("/reset-password", async (req, res) => {
  const { resetToken, newPassword } = req.body;

  // Verify the reset token
  try {
    const decoded = jwt.verify(resetToken, process.env.JWT_SECRET);

    // Find the user
    const user = await User.findById(decoded.userId);
    if (!user) {
      return res.status(400).json({ message: "User not found" });
    }

    // Hash the new password
    const hashedPassword = await bcrypt.hash(newPassword, 10);
    user.password = hashedPassword;
    await user.save();

    res.status(200).json({ message: "Password reset successfully." });
  } catch (err) {
    res.status(400).json({ message: "Invalid or expired reset token." });
  }
});

module.exports = router;
