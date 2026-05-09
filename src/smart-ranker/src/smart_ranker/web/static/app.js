const renderList = (elementId, items, formatter) => {
  const element = document.getElementById(elementId);
  element.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("li");
    empty.textContent = "empty";
    element.appendChild(empty);
    return;
  }

  for (const item of items) {
    const listItem = document.createElement("li");
    listItem.textContent = formatter(item);
    element.appendChild(listItem);
  }
};

const fetchJson = async (url, options = undefined) => {
  const response = await fetch(url, options);
  return response.json();
};

const refresh = async () => {
  const [personGroups, categories, policies, models, ledger] = await Promise.all([
    fetchJson("/api/person-groups"),
    fetchJson("/api/categories"),
    fetchJson("/api/policies"),
    fetchJson("/api/models"),
    fetchJson("/api/event-ledger"),
  ]);

  renderList("person-groups", personGroups, (item) => `${item.display_name} (${item.group_key})`);
  renderList("categories", categories, (item) => `${item.display_name} [${item.category_key}]`);
  renderList("policies", policies, (item) => `${item.display_name} / ${item.execution_mode}`);
  renderList("models", models, (item) => `${item.runId ?? "no-run"} @ ${item.trainedAt ?? "n/a"}`);
  renderList("ledger-feedback", ledger.feedbackEvents, (item) => `${item.feedback_type} / ${item.immich_asset_id}`);
  renderList("ledger-traces", ledger.inferenceTraces, (item) => `${item.immich_asset_id} / ${item.final_score}`);
  renderList("ledger-actions", ledger.actionExecutionLogs, (item) => `${item.action_type} / ${item.status}`);
};

const installJobButtons = () => {
  const output = document.getElementById("job-output");
  for (const button of document.querySelectorAll("[data-job]")) {
    button.addEventListener("click", async () => {
      const jobType = button.dataset.job;
      const payload = await fetchJson(`/api/jobs/${jobType}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ trigger: "manual-ui" }),
      });
      output.textContent = JSON.stringify(payload, null, 2);
    });
  }
};

installJobButtons();
refresh();
