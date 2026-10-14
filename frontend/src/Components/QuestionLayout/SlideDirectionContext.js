import { createContext, useContext } from "react";

// Provided by the question-wizard layout route (App.jsx) so any page deep in
// the tree (QuestionLayout, RoomCatalog) can pick the right carousel slide
// direction without prop-drilling through every Question*.jsx page.
export const SlideDirectionContext = createContext(1);

export function useSlideDirection() {
  return useContext(SlideDirectionContext);
}
