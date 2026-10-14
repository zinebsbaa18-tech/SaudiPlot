import { useState } from 'react';
import './Result.css';
import { useNavigate } from 'react-router-dom';

const Result = () => {
    const navigate = useNavigate();
  const [rooms, setRooms] = useState([
    { id: 1, name: 'غرفة نوم رئيسية – ماستر', count: 2, note: null },
    { id: 2, name: 'غرفة نوم', count: 3, note: null },
    { id: 3, name: 'حمام', count: 2, note: null },
    { id: 4, name: 'غرفة مجلس – نتظل', count: 1, note: 'الساحة' },
    { id: 5, name: 'صالة تلفزيون', count: 1, note: null },
    { id: 6, name: 'مطبخ رئيسي', count: 1, note: null },
    { id: 7, name: 'مطبخ استعراضي', count: 1, note: 'الساحة' },
    { id: 8, name: 'مجلس رجال', count: 1, note: null },
    { id: 9, name: 'مقاطع طعام', count: 1, note: null },
    { id: 10, name: 'حمام ومغاسل ضيوف', count: 1, note: 'الكل' },
    { id: 11, name: 'غرفة سائق بخدمات', count: 1, note: null },
    { id: 12, name: 'غسيل ملابس', count: 0, note: null },
    { id: 13, name: 'مستودع', count: 0, note: null },
  ]);

  const selectedTags = [
    { label: 'غرفة نوم رئيسية - غرفة', color: 'red' },
    { label: 'نوم - 2 غرفة', color: 'red' },
    { label: 'نوم - 3 غرفة', color: 'red' },
    { label: 'نوم - 4 غرفة', color: 'red' },
    { label: 'صالة كبار', color: 'orange' },
    { label: 'مجلس رجال', color: 'orange' },
    { label: 'مطبخ راكب', color: 'orange' },
    { label: 'مطبخ مفتوح', color: 'orange' },
    { label: 'سفرة كبار', color: 'green' },
    { label: 'مطبخ كبار', color: 'green' },
    { label: 'مستودع كبار', color: 'green' },
    { label: 'مطبخ كبار', color: 'green' },
    { label: 'حمام ضيوف كبار', color: 'blue' },
    { label: 'حمام ضيوف كبار', color: 'blue' },
    { label: 'حمام ضيوف كبار', color: 'blue' },
  ];

  const updateCount = (id, delta) => {
    setRooms(prev => prev.map(room => 
      room.id === id ? { ...room, count: Math.max(0, room.count + delta) } : room
    ));
  };

  return (
    <div className="room-catalog-wrapper" dir="rtl">
      <div className="room-catalog-container">
        {/* Header */}
        <div className="room-catalog-header">
          <h2 className="room-catalog-title">فراغات بيتك – عيّنها من إجاباتك، عتل ما تشاء</h2>
          <p className="room-catalog-subtitle">كل فراغ بيتك يمكنك اختيار فراغاتك – وسيتم لك التنسيق عقب اختيارك</p>
        </div>

        {/* Main Layout - DOM order: Catalog first, Tags second */}
        {/* In RTL, first item goes RIGHT, second goes LEFT */}
        {/* So visually: LEFT = Tags, RIGHT = Catalog */}
        <div className="room-catalog-layout">

          {/* LEFT COLUMN (visually): Room Catalog - placed SECOND in DOM */}
          <div className="room-catalog-card room-catalog-left">
            <h3 className="room-catalog-section-title">كتالوج الفراغات</h3>

            <div className="rooms-list">
              {rooms.map((room) => (
                <div key={room.id} className="room-item">

                  <div className="room-name-wrapper">
                    <span className="room-name">{room.name}</span>
                    {room.note && (
                      <span className={`room-note ${room.note === 'الكل' ? 'room-note-blue' : ''}`}>
                        {room.note}
                      </span>
                    )}
                  </div>

                  <div className="room-counter">
                    <button className="counter-btn" onClick={() => updateCount(room.id, -1)}>−</button>
                    <span className="counter-value">{room.count}</span>
                    <button className="counter-btn" onClick={() => updateCount(room.id, 1)}>+</button>
                  </div>

                </div>
              ))}
            </div>
          </div>

          {/* RIGHT COLUMN (visually): Room Selection - placed FIRST in DOM */}
          <div className="room-catalog-card room-catalog-right">
            <h3 className="room-catalog-section-title">فراغات بيتك</h3>

            <div className="room-tags-container">
              {selectedTags.map((tag, idx) => (
                <span key={idx} className={`room-tag room-tag-${tag.color}`}>
                  {tag.label}
                </span>
              ))}
            </div>

            <div className="success-banner">
              <span className="success-icon">✓</span>
              <span>تم تخصيص إجمالي 4,800.00 ريال سعودي</span>
            </div>

            <button className="btn-primary" onClick={() => navigate("/result-3d")}>
              ابدأ تصميم مختلفتي ←
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Result;