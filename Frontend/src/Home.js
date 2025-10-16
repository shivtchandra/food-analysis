import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "./context/AuthContext";
import StickerField from "./StickerField.jsx";
import heroImg from "./assets/hero.jpg";
import "./home.css";

export default function Home() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const requireAuth = (target) => {
    if (user) return navigate(target);
    navigate("/login", { state: { from: { pathname: target } } });
  };

  return (
    <div className="home-wrapper">
      <StickerField
        count={18}
        stickers={["🍎", "🥗", "🍳", "🍓", "🥛", "🍪", "💪", "🥕"]}
        seed={1001}
      />

      {/* ---------------- HERO ---------------- */}
      <section className="home-hero">
  <div className="hero-text">
    <h1>
      Smarter Food Insights,
      <br />
      <span className="accent">AI-powered & effortless</span>
    </h1>
    <p>
      Upload a receipt or screenshot — extract meals, compute macros &
      micronutrients, and track your progress over time.
    </p>

    <div className="hero-buttons">
      <button className="btn btn-primary">📸 Upload Screenshot</button>
      <button className="btn btn-secondary">⤓ Upload CSV</button>
      <button className="btn btn-secondary">🗓 Daily Log</button>
      <button className="btn btn-outline">View Analytics →</button>
    </div>
  </div>

  <div className="hero-right">
    <div className="hero-card">
      <img src={heroImg} alt="Meal Icon" />
      <h3>AI Meal Scan</h3>
      <p>Smart OCR and nutrition matching — try it after login.</p>
    </div>
  </div>
</section>

      {/* ---------------- QUICK METRICS ---------------- */}
      <section className="metrics-highlight">
        <h2 className="section-title">Instant Insights at a Glance</h2>
        <p className="section-sub">
          FoodX simplifies nutrition — from calories to micronutrients — giving you
          clarity and balance in every meal.
        </p>

        <div className="metrics-grid">
          <div className="metric-card">
            <h3>🔥 Energy (kcal)</h3>
            <p>See total calories instantly, with per-item contribution and %DV to daily goal.</p>
          </div>
          <div className="metric-card">
            <h3>💪 Protein (g)</h3>
            <p>Track protein density to optimize performance, satiety, and muscle repair.</p>
          </div>
          <div className="metric-card">
            <h3>🧂 Sodium (mg)</h3>
            <p>Monitor high-salt meals and spot trends that impact hydration and BP.</p>
          </div>
          <div className="metric-card">
            <h3>🍊 Vitamins & Minerals</h3>
            <p>Identify deficiencies through AI-driven micronutrient estimation.</p>
          </div>
        </div>
      </section>

      {/* ---------------- PROGRESS FEATURES ---------------- */}
      <section className="progress-section" style={{ background: "linear-gradient(180deg,#fffaf0 0%,#fff6e6 100%)" }}>
        <h2 className="section-title">Progress You Can See</h2>
        <p className="section-sub">Powerful dashboards to visualize how your nutrition evolves.</p>

        <div className="progress-grid">
          <div className="progress-card">
            <h3>📊 Daily Nutrition Summary</h3>
            <p>
              Every day’s intake summarized by energy, macros, and key vitamins — with
              intelligent visualizations.
            </p>
          </div>
          <div className="progress-card">
            <h3>🧠 AI Insights</h3>
            <p>
              Get personalized insights like “Low Vitamin D week” or “Improved protein balance”.
            </p>
          </div>
          <div className="progress-card">
            <h3>📅 Trends & History</h3>
            <p>
              Seamlessly track past logs, habits, and improvements with visual data.
            </p>
          </div>
        </div>
      </section>

      {/* ---------------- WHY FOODX / METRICS ---------------- */}
      <section className="about-section">
        <h2 className="section-title">Why Our Metrics Matter</h2>
        <p className="section-sub">
          We use verified data from <strong>FoodData Central</strong> and custom AI models
          to map every ingredient to accurate nutritional profiles.
        </p>

        <ul className="metrics-list">
          <li>🌿 Calorie & macronutrient computation from meal images.</li>
          <li>💧 Sodium, sugar, and fat balance comparison to daily reference.</li>
          <li>🧬 Micronutrient extraction — iron, calcium, vitamin C, and more.</li>
          <li>📈 Adaptive accuracy: the more you log, the smarter the predictions.</li>
        </ul>

        <div className="about-buttons">
          <Link to="/metrics" className="btn-primary">Learn More</Link>
          <button className="btn-secondary" onClick={() => requireAuth("/login")}>
            Try Now →
          </button>
        </div>
      </section>

      {/* ---------------- WHATS NEW ---------------- */}
      <section className="whatsnew-section" style={{ background: "#1b1b1b", color: "#fff" }}>
        <h2 className="section-title">What’s New</h2>
        <div className="whatsnew-grid">
          <div className="whatsnew-card">
            <h3>⚡ Micronutrient Extraction</h3>
            <p>Deeper vitamin-level analysis for better balance tracking.</p>
          </div>
          <div className="whatsnew-card">
            <h3>🚀 Faster OCR</h3>
            <p>Enhanced AI model for clearer meal text extraction.</p>
          </div>
          <div className="whatsnew-card">
            <h3>🧾 Auto Summaries</h3>
            <p>Quick visual breakdowns and daily summaries generated automatically.</p>
          </div>
        </div>
      </section>

      {/* ---------------- CTA ---------------- */}
      <section className="cta-section">
        <h2>Start Your Nutrition Journey Today</h2>
        <p>AI-powered insights built for awareness, balance, and smarter choices.</p>
        <button className="btn-primary" onClick={() => requireAuth("/login")}>
          Get Started →
        </button>
      </section>

      {/* ---------------- FOOTER ---------------- */}
      <footer className="home-footer">
        <small>© {new Date().getFullYear()} FoodX — Intelligent Nutrition Analytics.</small>
      </footer>
    </div>
  );
}
