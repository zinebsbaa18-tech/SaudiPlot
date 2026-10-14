// Carousel-style slide+fade+scale used to transition between wizard steps.
// `direction` is +1 moving forward (next), -1 moving backward (back).
export const slideVariants = {
  enter: (direction) => ({
    x: direction > 0 ? 80 : -80,
    opacity: 0,
    scale: 0.98,
  }),
  center: {
    x: 0,
    opacity: 1,
    scale: 1,
  },
  exit: (direction) => ({
    x: direction > 0 ? -80 : 80,
    opacity: 0,
    scale: 0.98,
  }),
};

export const slideTransition = {
  x: { type: "spring", stiffness: 300, damping: 32 },
  opacity: { duration: 0.25 },
  scale: { duration: 0.3 },
};
