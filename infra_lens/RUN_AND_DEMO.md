# InfraLens — run & demo guide

## 1. Run it
From inside the `readycheck/` folder:

```
pip install -r requirements.txt
python -m py_compile app.py      # optional: confirms no syntax errors (no output = good)
python app.py
```

Open **http://localhost:5000**

Put your real key in `.env`:
```
CEREBRAS_API_KEY=sk-...your-key...
```

## 1b. What you can feed it
InfraLens now accepts **two GCP input formats**, auto-detected — drop one or both,
even several files at once:
- **Terraform state** (`.tfstate`)
- **GCP Cloud Asset Inventory** export (`.json`), from
  `gcloud asset export --content-type=resource ...` — handles a JSON array,
  a `{ "assets": [...] }` wrapper, or newline-delimited JSON.
Resources from both are normalised and merged; the same resource seen in both
formats is counted once.

### The upload is the cloud
There is no upload box. **Drag your files straight onto the rotating 3D cloud**
(or click it to browse). Each file gets absorbed with a pulse and then orbits the
cloud as a glowing node; loaded files also show as chips on the left, with an ×
to remove. "Load demo data" drops a demo node so you can show the flow with no file.

## 2. Two ways the demo works
- **With a working Cerebras key + model**: clicking Inspect fires all five agents in
  parallel on Cerebras, you get real findings and real parallel timings.
- **Safety net (automatic)**: if the key is missing, the network drops, or the model
  name is wrong, the app silently falls back to a bundled, realistic report so the
  demo NEVER breaks on camera. A tiny note appears under the report when this happens.

> Model name lives in ONE place in `app.py`: `MODEL = "gemma-4-31b"`. If Cerebras
> rejects it, change only that line. Until then the safety net covers you.

## 3. 60-second demo script
- **0–7s (hook):** "You built something on GCP. But is it ready — to scale, to
  survive, to be observed, to iterate fast? InfraLens runs six AI agents
  simultaneously across your Terraform state and tells you in seconds."
- **7–18s (start):** Show the rotating 3D cloud. Click **Load demo data** (filename +
  context auto-fill), then **Inspect Infrastructure**. Watch the cloud dissolve and
  all five pipeline dots fire at once.
- **18–35s (speed):** Dots complete with times. Point at the speed cards — Cerebras
  time in mint vs estimated GPU baseline in coral. "Six agents. Gemma 4 on Cerebras.
  All at the same time. Google's model inspecting GCP against Google's own docs."
- **35–50s (results):** Executive summary card. Click the Cost lens (estimated spend +
  top optimisation), then Resilience (single point of failure: the database). Show the
  Cross-Lens Surface — payments-db flagged by three lenses at once. Glance at What You
  Built Well.
- **50–60s (close):** Scroll to the three-tier Action Plan. Expand the STRIDE Surface
  at the bottom. End on the small rotating cloud in the top-right. "InfraLens. Point
  it at your cloud."

## 4. Before recording
- Close all tabs except localhost:5000. Disable notifications.
- Nothing sensitive on screen. The key only lives in `.env`, never in the UI.

## 5. Submit
- Track 3: post in **#g4hackathon-enterprise-impact** with the project description.
- Track 2: post in **#g4hackathon-people-choice** + the demo video on X tagging
  @Cerebras and @googlegemma.
- Deadline: Mon June 29, 10:00 AM PT (resubmits allowed).
