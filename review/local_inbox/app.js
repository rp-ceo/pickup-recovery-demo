const byId = id => document.getElementById(id);
const form = byId("form");
const email = byId("email");
const record = byId("record");
const example = byId("example");
const reset = byId("reset");
const status = byId("status");
const thread = byId("thread");
let session = null;

example.onclick = () => {
  email.value = session
    ? "Thursday works for me"
    : "The box is still by my door. I kept the whole afternoon free for nothing.";
  email.focus();
};

reset.onclick = () => {
  session = null;
  thread.replaceChildren();
  email.value = "";
  record.disabled = false;
  reset.hidden = true;
  example.textContent = "Use example email";
  example.hidden = false;
  status.textContent = "";
  email.focus();
};

function element(tag, text) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  return item;
}

function message(title, text, style) {
  const item = element("div");
  item.className = "message " + style;
  item.append(element("strong", title), element("p", text));
  return item;
}

function interpretation(decision, model) {
  const label = decision.intent.replaceAll("_", " ");
  switch (decision.source) {
    case "rules":
      return "The reply matched an existing rule (" + label + ").";
    case "unavailable":
      return "The local model could not be reached. This email could not be classified.";
    case "invalid_response":
      return "The local model returned an unusable answer.";
    case "unresolved":
      return model + " could not identify a specific request.";
    default:
      return model + " interpreted the email as “" + (label === "pickup" ? "missed pickup" : label) + "”.";
  }
}

function showTurn(input, data) {
  const turn = element("section");
  turn.append(message("Shopper", input, "shop"));
  for (const decision of data.decisions) {
    const title = decision.source === "rules" ? "Reply rules" : "Local model";
    turn.append(message(title, interpretation(decision, data.model), "model"));
  }
  if (data.decisions.length === 0) {
    turn.append(message("Case workflow", "The existing case and reply rules handled this message.", "model"));
  }
  if (data.calls.length) {
    const details = element("details");
    const list = element("ol");
    for (const call of data.calls) {
      const result = typeof call.result === "string" ? call.result : JSON.stringify(call.result);
      list.append(element("li", call.tool + " → " + result));
    }
    details.append(element("summary", "Show " + data.calls.length + " simulated tool calls"), list);
    turn.append(details);
  }
  turn.append(message("Pickup agent", data.message, "reply"));
  const state = element("span", "Case status · " + data.state.toLowerCase().replaceAll("_", " "));
  state.className = "case-state";
  turn.append(state);
  thread.append(turn);
  email.value = "";
  example.hidden = data.state !== "OFFERED";
  example.textContent = "Choose Thursday";
  reset.hidden = false;
}

form.onsubmit = async event => {
  event.preventDefault();
  const input = email.value.trim();
  if (!input || byId("send").disabled) return;
  const controls = [byId("send"), record, reset, example, email];
  for (const control of controls) control.disabled = true;
  status.textContent = "Reading the email…";
  try {
    const response = await fetch("/turn", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({email: input, record: record.value, session}),
    });
    const data = await response.json();
    if (!response.ok) throw Error(data.error || "Unable to process email.");
    session = data.session;
    showTurn(input, data);
    status.textContent = "";
  } catch (error) {
    status.textContent = error.message;
  } finally {
    for (const control of controls) control.disabled = false;
    record.disabled = Boolean(session);
    email.focus();
  }
};
