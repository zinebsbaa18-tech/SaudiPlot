const commonProps = {
  viewBox: "0 0 24 24",
  width: 18,
  height: 18,
  fill: "none",
  "aria-hidden": true,
};

export function FamilyIcon() {
  return (
    <svg {...commonProps}>
      <circle cx="8" cy="7" r="2.6" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="16" cy="7" r="2.6" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M3.5 19c.4-2.8 2.2-4.3 4.5-4.3s4.1 1.5 4.5 4.3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path
        d="M11.5 19c.4-2.8 2.2-4.3 4.5-4.3s4.1 1.5 4.5 4.3"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function AccessibilityIcon() {
  return (
    <svg {...commonProps}>
      <circle cx="12" cy="4.5" r="1.8" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M12 8v5m0 0-3.5 5M12 13l3.5 5M8 11h8"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function HospitalityIcon() {
  return (
    <svg {...commonProps}>
      <path
        d="M5 10h11a1 1 0 0 1 1 1c0 4.4-2.9 7.5-6.5 7.5S4 15.4 4 11a1 1 0 0 1 1-1Z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M16 11.5h1.5a2 2 0 0 1 0 4H16"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
      />
      <path d="M8 4.5c0 1.2-1 1.4-1 2.6s1 1.6 1 1.6M12 4.5c0 1.2-1 1.4-1 2.6s1 1.6 1 1.6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}

export function KitchenIcon() {
  return (
    <svg {...commonProps}>
      <circle cx="12" cy="12.5" r="7" stroke="currentColor" strokeWidth="1.6" />
      <circle cx="12" cy="12.5" r="2.6" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12 3.5v2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

export function ServicesIcon() {
  return (
    <svg {...commonProps}>
      <rect x="3.5" y="8" width="17" height="10.5" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path
        d="M8.5 8V6.5a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2V8"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path d="M3.5 12.5h17" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

export function ClipboardIcon() {
  return (
    <svg {...commonProps}>
      <rect x="5" y="4.5" width="14" height="16" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M9 4.5h6a1 1 0 0 1 1 1v1a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1v-1a1 1 0 0 1 1-1Z" stroke="currentColor" strokeWidth="1.6" />
      <path d="M8.5 12h7M8.5 15.5h7M8.5 19h4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}
