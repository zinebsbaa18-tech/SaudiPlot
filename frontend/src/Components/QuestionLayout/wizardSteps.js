import {
  FamilyIcon,
  AccessibilityIcon,
  HospitalityIcon,
  KitchenIcon,
  ServicesIcon,
  ClipboardIcon,
} from "../WizardIcons/WizardIcons";

export const WIZARD_STEPS = [
  { path: "/questions/1", labelKey: "steps.family", Icon: FamilyIcon },
  { path: "/questions/2", labelKey: "steps.accessibility", Icon: AccessibilityIcon },
  { path: "/questions/3", labelKey: "steps.hospitality", Icon: HospitalityIcon },
  { path: "/questions/4", labelKey: "steps.kitchen", Icon: KitchenIcon },
  { path: "/questions/5", labelKey: "steps.services", Icon: ServicesIcon },
  { path: "/questions/6", labelKey: "steps.final", Icon: ClipboardIcon },
];
