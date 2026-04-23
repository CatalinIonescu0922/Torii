# Torri Web UI - Architecture & Setup Guide

This document explains the structure of the Torri React UI that was built and provides step-by-step instructions on how to run it. 

## What Was Built

The UI is designed as a **React Single Page Application (SPA)** that polls your Python orchestrator backend every 5 seconds for the latest CI/CD state. It is completely decoupled from any specific executor (like Jenkins).

Here is the breakdown of the files created in your workspace:

1. **`web/src/types/status.ts` (The Data Contract)**
   - Defines strict TypeScript interfaces (`Pipeline`, `Change`, `Job`) that match the JSON structure your backend should emit.
   
2. **`web/src/hooks/useStatusPolling.ts` (The Network Layer)**
   - A custom React hook that executes the 5-second interval HTTP `GET` request.
   - It manages `loading`, `error`, and `polling` states, and provides a function to pause/resume auto-refreshing so the UI doesn't jump while a user is reading a log.

3. **`web/src/components/Dashboard.tsx` (The Visuals)**
   - Uses Tailwind CSS utility classes to render the dashboard.
   - Displays pipelines (e.g., `check`, `gate`).
   - Shows Gerrit changes within each pipeline.
   - Renders individual jobs as badges with dynamic color-coding based on generic statuses (`queued`, `running`, `success`, `failed`, `canceled`).

4. **`backend_example.py` (The Mock Backend)**
   - Found in the root directory. It contains a mock FastAPI service that returns dummy data perfectly matching what the React UI expects.

---

## How to Set Up and Run the UI

*(Note: The initial terminal command to scaffold the React app was cancelled, so you will need to run the scaffolding commands to initialize the web folder properly before using the components.)*

### Step 1: Initialize the React/Vite Project
Open a terminal, navigate to the Torri workspace root, and run these commands to set up the React app and install Tailwind CSS (required for the layout styling):

```bash
# Navigate to the web folder
cd web

# Scaffold a React + TypeScript app (if you haven't already)
npm create vite@latest . -- --template react-ts

# Install core dependencies
npm install

# Install Tailwind CSS for styling
npm install -D tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

### Step 2: Configure Tailwind
Edit `web/tailwind.config.js` to include the `src` folder so the classes in `Dashboard.tsx` work:
```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
```
Then add the Tailwind directives to your `web/src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

### Step 3: Mount the Dashboard
Edit `web/src/App.tsx` and replace its contents to mount the new Dashboard component:
```tsx
import { Dashboard } from './components/Dashboard';

function App() {
  return <Dashboard />;
}

export default App;
```

### Step 4: Run the Mock Backend and Frontend

**Start the Python Backend (Terminal 1):**
```bash
# In the root Torri directory
source microservices/Torri/.venv/bin/activate
pip install fastapi uvicorn
uvicorn backend_example:app --reload --port 8000
```

**Start the React UI (Terminal 2):**
```bash
cd web
# Start the Vite development server
npm run dev
```

*Note: To prevent CORS issues during local development, ensure your Vite config (`web/vite.config.ts`) proxies `/api` requests to `http://localhost:8000`, or simply rely on the CORS middleware already added in `backend_example.py`!*
