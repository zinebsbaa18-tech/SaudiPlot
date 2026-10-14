import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import Navbar from "../../Components/Navbar/Navbar";
import Button from "../../Components/Button/Button";
import Stepper from "../../Components/Stepper/Stepper";
import usePageTitle from "../../hooks/usePageTitle";
import { useFormStore } from "../../Store/useFormStore";
import { useSlideDirection } from "../../Components/QuestionLayout/SlideDirectionContext";
import { slideVariants, slideTransition } from "../../Components/QuestionLayout/slideVariants";
import "./RoomCatalog.css";

export default function RoomCatalog() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  const CATEGORIES = [
    {
      title: t("room_catalog.cat_bedrooms"),
      rooms: [
        { id: "master", label: t("room_catalog.master") },
        { id: "bedroom", label: t("room_catalog.bedroom") },
        { id: "bathroom", label: t("room_catalog.bathroom") },
        { id: "closet", label: t("room_catalog.closet"), auto: true },
      ],
    },
    {
      title: t("room_catalog.cat_living"),
      rooms: [
        { id: "living", label: t("room_catalog.living") },
        { id: "kitchen", label: t("room_catalog.kitchen") },
        { id: "prepKitchen", label: t("room_catalog.prep_kitchen"), auto: true },
      ],
    },
    {
      title: t("room_catalog.cat_hospitality"),
      rooms: [
        { id: "majlis", label: t("room_catalog.majlis") },
        { id: "dining", label: t("room_catalog.dining"), auto: true },
        { id: "guestBath", label: t("room_catalog.guest_bath"), auto: true },
      ],
    },
    {
      title: t("room_catalog.cat_services"),
      rooms: [
        { id: "driver", label: t("room_catalog.driver_room") },
        { id: "laundry", label: t("room_catalog.laundry") },
        { id: "storage", label: t("room_catalog.storage") },
      ],
    },
  ];

  const SUMMARY_TAGS = [
    { label: "رئيسية · 28م²", color: "pink" },
    { label: "نوم 2 · 16م²", color: "green" },
    { label: "نوم 3 · 16م²", color: "green" },
    { label: "نوم 4 · 14م²", color: "green" },
    { label: "حمام رئيسي · 8م²", color: "purple" },
    { label: "حمام · 6م²", color: "purple" },
    { label: "ملابس · 6م²", color: "pink" },
    { label: "صالة · 38م²", color: "gray" },
    { label: "مطبخ · 20م²", color: "yellow" },
    { label: "تحضيري · 8م²", color: "yellow" },
    { label: "مجلس · 30م²", color: "blue" },
    { label: "مقطع طعام · 16م²", color: "blue" },
    { label: "حمام ضيوف · 5م²", color: "purple" },
    { label: "غسيل · 8م²", color: "gray" },
  ];

  const counts = useFormStore((state) => state.roomCatalog);
  const setRoomCount = useFormStore((state) => state.setRoomCount);

  const totalRooms = Object.values(counts).reduce((sum, value) => sum + value, 0);
  const direction = useSlideDirection();

  return (
    <motion.div
      className="page page--carousel"
      custom={direction}
      variants={slideVariants}
      initial="enter"
      animate="center"
      exit="exit"
      transition={slideTransition}
    >
      <Navbar />
      <main className="room-catalog">
        <h1 className="room-catalog__title">
          {t("room_catalog.title")}
        </h1>
        <p className="room-catalog__subtitle">
          {t("room_catalog.subtitle")}
        </p>

        <div className="room-catalog__layout">
          <section className="room-catalog__catalog">
            <h2 className="room-catalog__section-title">{t("room_catalog.section_title")}</h2>
            {CATEGORIES.map((category) => (
              <div className="room-catalog__group" key={category.title}>
                <p className="room-catalog__group-title">{category.title}</p>
                {category.rooms.map((room) => (
                  <Stepper
                    key={room.id}
                    label={room.label}
                    value={counts[room.id]}
                    onChange={(value) => setRoomCount(room.id, value)}
                    badge={room.auto ? t("stepper.auto") : undefined}
                  />
                ))}
              </div>
            ))}
          </section>

          <aside className="room-catalog__summary">
            <div className="room-catalog__summary-header">
              <h2 className="room-catalog__section-title">{t("room_catalog.summary_title")}</h2>
              <span className="room-catalog__count">{t("room_catalog.count", { count: totalRooms })}</span>
            </div>

            <div className="room-catalog__tags">
              {SUMMARY_TAGS.map((tag) => (
                <span key={tag.label} className={`room-catalog__tag room-catalog__tag--${tag.color}`}>
                  {tag.label}
                </span>
              ))}
            </div>

            <p className="room-catalog__banner">
              {t("room_catalog.banner")}
            </p>

            <Button fullWidth onClick={() => navigate("/generating")}>
              {t("room_catalog.btn")}
            </Button>
          </aside>
        </div>
      </main>
    </motion.div>
  );
}
