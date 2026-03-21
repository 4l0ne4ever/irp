import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { RunProvider } from "./context/RunContext.jsx";
import { MonitoringProvider } from "./context/MonitoringContext.jsx";
import { WebSocketBridge } from "./components/WebSocketBridge.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <RunProvider>
      <MonitoringProvider>
        <WebSocketBridge />
        <App />
      </MonitoringProvider>
    </RunProvider>
  </React.StrictMode>
);
