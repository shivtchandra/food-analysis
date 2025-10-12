// src/PhotoSlideshow.jsx
import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

/**
 * Modern slideshow (no blur). Designed to sit *under* StickerField.
 * Use in App.js as before: <PhotoSlideshow images={[bg1,bg3]} interval={5000} />
 */

export default function PhotoSlideshow({ images = [], interval = 5000, ken = true }) {
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (!images || images.length <= 1) return;
    const t = setInterval(() => setIndex((i) => (i + 1) % images.length), interval);
    return () => clearInterval(t);
  }, [images, interval]);

  return (
    <div className="photo-slideshow no-blur">
      <AnimatePresence>
        {images && images.length > 0 && (
          <motion.img
            key={index}
            src={images[index]}
            alt=""
            className={`slide-image ${ken ? "animate" : ""}`}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 1.2, ease: "easeInOut" }}
            draggable="false"
          />
        )}
      </AnimatePresence>
      {/* Keep a subtle parallax glow layer (optional) */}
      <div className="parallax-layer" aria-hidden="true" />
    </div>
  );
}
