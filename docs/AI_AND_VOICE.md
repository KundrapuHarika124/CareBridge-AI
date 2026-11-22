
# AI assistant and voice

## Design rule

The language model is a parser, not an agent. It is asked for a small JSON object describing
what the user said. It never writes the words the user sees, never chooses a doctor, and
cannot book, cancel or change anything. Those are done by ordinary code that can be tested.

```
user text or speech
   → safety check (rules)
   → extraction (Gemini if configured, otherwise rules)        fields only
   → state machine (pure Python)                               decides next step
   → reply from fixed Telugu or English templates
   → booking only via a server-issued confirmation token
```

## Modes

| Mode | When | Behaviour |
|---|---|---|
| `ai` | `LLM_PROVIDER=gemini` with a working key | Free sentences in Telugu, English or a mix are parsed into specialty, area, day, time of day |
| `guided` | `LLM_PROVIDER=none`, or the provider failed | A rule-based extractor handles common phrases; every step also offers buttons. The screen says guided mode is on |
| `mock` | `LLM_PROVIDER=mock` | Development only, refused when `APP_ENV=production`. Never presented as real AI |

If a Gemini call fails mid-conversation (timeout, quota, malformed output) that turn falls
back to the rule-based extractor. A 429 is not retried, to avoid burning free quota.

## Conversation states

`IDENTIFYING_PATIENT` (caregivers with more than one patient) → `UNDERSTANDING_REQUEST` →
`IDENTIFYING_SPECIALTY` → `COLLECTING_LOCATION` → `COLLECTING_PREFERENCES` →
`SHOWING_AVAILABLE_SLOTS` → `AWAITING_CONFIRMATION` → `BOOKED`. `CANCELLED` and
`HANDOFF_REQUIRED` are the other end states. Sessions expire after 15 idle minutes.

## Safety rules

| Rule | Implementation |
|---|---|
| Emergencies | A list of English, Telugu and romanised Telugu phrases (chest pain, cannot breathe, unconscious, heavy bleeding, stroke signs, suicidal statements and others), matched on word boundaries. A match pauses booking and shows 112 and 108. The list is a demonstration list, **not clinically reviewed, and will miss cases** |
| No medical advice | Questions about medicines, doses, diagnosis or whether something is serious get a fixed refusal and an offer to book a doctor |
| Confirmation | "Yes" is accepted only from a short reply (three words or fewer) matched by rules. Anything doubtful counts as "no". The model's opinion on yes or no is discarded |
| One slot, one token | The confirmation token is bound to one slot and expires in 5 minutes. Changing anything issues a new one |
| Low-confidence speech | Voice input with recogniser confidence below 0.6 is read back for confirmation instead of acted on |
| Getting stuck | After 3 unclear turns the assistant stops and points to manual booking |
| Honesty | "Booked" is said only after the booking transaction commits. If the slot was taken meanwhile, the user is told and shown alternatives |
| Labelling | Department suggestions and intake questions carry `DEMO_UNREVIEWED` and the UI says so |

## AI summary of intake answers

- Only the patient can request it, and only from their own saved answers.
- The model is told to restate, not interpret: no diagnosis, no advice, and to list what is
  unclear or missing.
- The result is labelled "AI-generated". The patient can edit it. **Nobody else can see it
  until the patient marks it correct.** The doctor always has the raw answers.
- With no model configured the endpoint returns `AI_UNAVAILABLE`. No summary is invented.

## What is sent to Google

| Call | Sent | Not sent |
|---|---|---|
| Extraction | The user's message for that turn, the list of specialty codes and localities, the state name | Name, phone, email, ids, appointment history |
| Summary | The intake questions and the patient's typed answers | Name, phone, email, ids |

Free text can contain anything a user types. On the Gemini free tier, Google states that
content may be used to improve its products, so **the free tier is suitable for synthetic
data only**. The UI warns against entering real details. Prompts and keys are never logged.

## Voice

- Provider: Azure Speech (`te-IN` and `en-IN` recognition; neural voices
  `te-IN-ShrutiNeural` and `en-IN-NeerjaNeural` by default, changeable in `frontend/.env`).
- The backend exchanges its subscription key for a token valid about 10 minutes
  (`POST /speech/token`). The browser uses the Speech SDK with that token. The key never
  reaches the browser. Audio never passes through or is stored by CareBridge.
- The user chooses the language with the Telugu / English switch; automatic language
  detection is not used.
- With `SPEECH_PROVIDER=none` the microphone button is not shown and a notice explains that
  typing and buttons are available. Microphone refusal, silence and network failure each
  have their own message.
- The browser's built-in speech synthesis is **not** used as a fallback, because Telugu
  voices are missing on many devices and a silent failure would be worse than a clear notice.

## Not verified

No request has been made to Gemini or Azure from this code. Model name, voice names,
endpoint shapes and SDK calls are written from documentation and must be confirmed on first
use. See COST_AND_FREE_TIER.md for what to check.
