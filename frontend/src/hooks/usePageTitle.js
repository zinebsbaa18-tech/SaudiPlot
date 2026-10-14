import { useEffect } from "react";

export default function usePageTitle(title) {
  useEffect(() => {
    const prev = document.title;
    document.title = title ? `${title} — عَمِّر أرضك` : "عَمِّر أرضك — صمّم بيتك السعودي";
    return () => { document.title = prev; };
  }, [title]);
}
