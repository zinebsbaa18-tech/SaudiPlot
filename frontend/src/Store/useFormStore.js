import { create } from "zustand";
import deedTemplate from "../../objects/format.json";
import * as Api from "../Api/Api";

// Maps the UI answer values onto the backend JSON shape (objects/format.json).
const GUEST_RECEPTION = {
  independent: { type: "majlis_separate", label: "مجلس رجال بمدخل مستقل" },
  split: { type: "majlis_two", label: "مجلسان — رجال ونساء" },
  "living-room": { type: "living_room", label: "تكفي الصالة" },
};

const KITCHEN = {
  "مفتوح على الصالة": { type: "open", label: "مفتوح على الصالة" },
  مغلق: { type: "closed", label: "مغلق" },
  "مغلق + مطبخ تحضيري": { type: "closed_with_pantry", label: "مغلق + مطبخ تحضيري" },
};

// Q5 service chips -> additional_rooms flags.
const SERVICE_FLAGS = {
  "غسيل وكيّ": "laundry_room",
  "غرفة عاملة منزلية بحمّام": "maid_room",
  "غرفة سائق بحمّام": "driver_room",
  "مدخل خدمة مستقل": "maid_entrance",
  مستودع: "storage_room",
};

function countRange(total) {
  if (total <= 4) return "2-4";
  if (total <= 7) return "5-7";
  if (total <= 10) return "8-10";
  return "10+";
}

export const useFormStore = create((set, get) => ({
  // Static deed data (mock; replaced by backend OCR later).
  deed: deedTemplate,

  // Raw JSON extracted by Gemini from the uploaded deed image.
  extractedDeedRaw: null,
  setExtractedDeedRaw: (data) => set({ extractedDeedRaw: data }),

  // Plot dimensions in metres. Always required before leaving the deed step —
  // the deed doesn't always carry explicit width/height, so the user must
  // confirm/enter both (see ConfirmData + ExtractionFailed).
  landDimensions: { width: "", height: "" },
  setLandDimensions: (landDimensions) => set({ landDimensions }),

  // GPS coordinates extracted from QR codes. Required before proceeding.
  landCoordinates: { lat: "", lng: "" },
  setLandCoordinates: (landCoordinates) => set({ landCoordinates }),

  // Plot orientation in degrees (0 = north-up), set via the rotation handle
  // on the map picker. Purely visual — lets the drawn rectangle match the
  // plot's real-world orientation instead of always being axis-aligned.
  landRotation: 0,
  setLandRotation: (landRotation) => set({ landRotation }),

  // Collected answers (UI-friendly form).
  familyMembers: { adults: 4, children: 3 },
  hasElderly: true,
  guestReceptionId: "independent",
  kitchenType: "مغلق + مطبخ تحضيري",
  services: ["غرفة عاملة منزلية بحمّام", "غرفة سائق بحمّام"],
  roomCatalog: {
    master: 1,
    bedroom: 3,
    bathroom: 2,
    closet: 1,
    living: 1,
    kitchen: 1,
    prepKitchen: 1,
    majlis: 1,
    dining: 1,
    guestBath: 1,
    driver: 1,
    laundry: 1,
    storage: 0,
  },

  setFamilyMembers: (familyMembers) => set({ familyMembers }),
  setHasElderly: (hasElderly) => set({ hasElderly }),
  setGuestReceptionId: (guestReceptionId) => set({ guestReceptionId }),
  setKitchenType: (kitchenType) => set({ kitchenType }),
  setServices: (services) => set({ services }),
  setRoomCount: (id, count) =>
    set((state) => ({ roomCatalog: { ...state.roomCatalog, [id]: count } })),

  // ── Backend wiring (behavioral only; the UI surface is frozen) ──────
  projectId: null,

  // Idempotent: anonymous session + project, remembered across refreshes.
  ensureProject: async () => {
    const project = await Api.ensureProject();
    set({ projectId: project.id });
    return project;
  },

  // Persist the confirmed plot data (ConfirmData / ExtractionFailed).
  savePlotToBackend: async (extra = {}) => {
    const state = get();
    const project = await get().ensureProject();
    const boundaries = state.extractedDeedRaw?.boundaries || null;
    return Api.savePlot(project.id, {
      width_m: Number(state.landDimensions.width),
      height_m: Number(state.landDimensions.height),
      latitude: state.landCoordinates.lat === "" ? null : Number(state.landCoordinates.lat),
      longitude: state.landCoordinates.lng === "" ? null : Number(state.landCoordinates.lng),
      rotation_deg: state.landRotation || 0,
      boundaries,
      source: state.extractedDeedRaw ? "deed_extraction" : "manual",
      ...extra,
    });
  },

  // Persist every questionnaire answer. Fire-and-forget from the question
  // screens; awaited before generation starts.
  saveBriefToBackend: async () => {
    const state = get();
    const project = await get().ensureProject();
    const payload = get().buildPayload();
    return Api.saveBrief(project.id, {
      family_preferences: payload.family_preferences,
      ui_answers: {
        familyMembers: state.familyMembers,
        hasElderly: state.hasElderly,
        guestReceptionId: state.guestReceptionId,
        kitchenType: state.kitchenType,
        services: state.services,
      },
    });
  },

  saveRoomProgramToBackend: async () => {
    const project = await get().ensureProject();
    return Api.saveRoomProgram(project.id, get().roomCatalog);
  },

  // Refresh restore: rebuild the store from the persisted backend state.
  restoreFromBackend: async () => {
    const projectId = Api.storedProjectId();
    if (!projectId) return false;
    try {
      await Api.ensureSession();
      const project = await Api.ensureProject();
      set({ projectId: project.id });
      const plot = await Api.getPlot(project.id).catch(() => null);
      if (plot) {
        set({
          landDimensions: { width: String(plot.width_m), height: String(plot.height_m) },
          landCoordinates: {
            lat: plot.latitude == null ? "" : String(plot.latitude),
            lng: plot.longitude == null ? "" : String(plot.longitude),
          },
          landRotation: plot.rotation_deg || 0,
        });
      }
      const brief = await Api.getBrief(project.id).catch(() => null);
      const ui = brief?.answers?.ui_answers;
      if (ui) {
        set({
          familyMembers: ui.familyMembers ?? get().familyMembers,
          hasElderly: ui.hasElderly ?? get().hasElderly,
          guestReceptionId: ui.guestReceptionId ?? get().guestReceptionId,
          kitchenType: ui.kitchenType ?? get().kitchenType,
          services: ui.services ?? get().services,
        });
      }
      return true;
    } catch {
      return false;
    }
  },

  // Assemble the full payload in the backend JSON shape.
  buildPayload: () => {
    const state = get();
    const { adults, children } = state.familyMembers;
    const total = adults + children;

    const additionalRooms = {
      laundry_room: false,
      maid_room: false,
      maid_entrance: false,
      storage_room: false,
      driver_room: false,
    };
    state.services.forEach((service) => {
      const flag = SERVICE_FLAGS[service];
      if (flag) additionalRooms[flag] = true;
    });

    return {
      ...state.deed,
      land_dimensions: {
        width_m: Number(state.landDimensions.width) || null,
        height_m: Number(state.landDimensions.height) || null,
      },
      family_preferences: {
        family_members: {
          count_range: countRange(total),
          estimated_count: total,
        },
        elderly_or_accessibility: { has_elderly: state.hasElderly },
        bedrooms: { count: state.roomCatalog.bedroom + state.roomCatalog.master },
        master_bedrooms: { count: state.roomCatalog.master },
        guest_reception: GUEST_RECEPTION[state.guestReceptionId],
        kitchen: KITCHEN[state.kitchenType],
        additional_rooms: additionalRooms,
        room_catalog: state.roomCatalog,
      },
    };
  },
}));
