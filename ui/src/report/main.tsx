import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../styles/base.css";
import "./report.css";
import Report from "./Report";

createRoot(document.getElementById("root")!).render(<StrictMode><Report /></StrictMode>);
