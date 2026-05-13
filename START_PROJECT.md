# Start Project

## 1. Start the stack
```bash
cd compose
./launch.sh --start
```
Wait until scheduler logs show `Waiting for events...` (~60s for Gerrit).

## 2. Start the UI (on your Mac)
```bash
cd web
npm install && npm run dev
```
Open `http://localhost:5173`

## 3. Create a test change in Gerrit
- Open `http://localhost:8087/g`
- Login: `torii` / `19D9aIn7zePb`
- Pick any project (e.g. `libraries/common-utils`) → **New Change** → any subject → **Create**
- This triggers `patchset-created` → change enters the **check** pipeline → jobs start (50s mock)

## 4. Trigger the gate pipeline
- Open the change → post any comment
- This triggers `comment-added` → change enters the **gate** pipeline

## 5. Watch it work

| What | Where |
|---|---|
| Scheduler logs | `compose/logs/scheduler/scheduler.log` |
| Status API | `http://localhost:8000/api/status` |
| Kafka UI | `http://localhost:8087/k` |
| Redis debug | `docker exec -it torii_redis redis-cli` then `GET torri:ui:status` |

Jobs show as **running** in the UI, flip to **success** after 50 seconds.

## Stop & clean
```bash
./launch.sh --delete
```
