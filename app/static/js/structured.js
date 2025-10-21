document.addEventListener("DOMContentLoaded", () => {
  const form = document.getElementById("structured-form");
  const fileInput = document.getElementById("structured-file");
  const statusEl = document.getElementById("structured-status");
  const resultCard = document.getElementById("structured-result-card");
  const summaryGrid = document.getElementById("structured-summary");
  const nldftBody = document.getElementById("structured-nldft");
  const rawPre = document.getElementById("structured-raw");

  const FIELD_LABELS = [
    ["sp_bet", "单点 BET 比表面积 (m²/g)"],
    ["mp_bet", "多点 BET 比表面积 (m²/g)"],
    ["total_pore_vol", "最高单点吸附总孔体积 (cm³/g)"],
    ["avg_pore_d", "单点总孔吸附平均孔径 (nm)"],
    ["most_probable", "最可几孔径 (nm)"],
    ["d10", "D10 (nm)"],
    ["d90", "D90 (nm)"],
    ["d90_d10_ratio", "D90 / D10"],
    ["pore_volume_A", "孔容 A (cm³/g)"],
    ["less_than_0_5D", "< 0.5D 百分比 (%)"],
    ["greater_than_1_5D", "> 1.5D 百分比 (%)"],
  ];

  function resetView() {
    statusEl.textContent = "";
    resultCard.hidden = true;
    summaryGrid.innerHTML = "";
    nldftBody.innerHTML = "";
    rawPre.textContent = "";
  }

  function formatNumber(value) {
    if (value === null || value === undefined || value === "") {
      return "-";
    }
    const num = Number(value);
    if (Number.isFinite(num)) {
      if (Math.abs(num) >= 1000 || Math.abs(num) < 0.01) {
        return num.toExponential(4);
      }
      return num.toFixed(6).replace(/\.?0+$/, "");
    }
    return String(value);
  }

  function renderSummary(data) {
    summaryGrid.innerHTML = "";
    FIELD_LABELS.forEach(([key, label]) => {
      const item = document.createElement("div");
      item.className = "result-item";
      const title = document.createElement("div");
      title.className = "result-title";
      title.textContent = label;
      const value = document.createElement("div");
      value.className = "result-value";
      value.textContent = formatNumber(data[key]);
      item.appendChild(title);
      item.appendChild(value);
      summaryGrid.appendChild(item);
    });
  }

  function renderNldftRows(rows) {
    nldftBody.innerHTML = "";
    rows.forEach((row) => {
      const tr = document.createElement("tr");
      const tdAvg = document.createElement("td");
      const tdVol = document.createElement("td");
      tdAvg.textContent = formatNumber(row.average_pore_diameter);
      tdVol.textContent = formatNumber(row.pore_integral_volume);
      tr.appendChild(tdAvg);
      tr.appendChild(tdVol);
      nldftBody.appendChild(tr);
    });
  }

  async function submitForm(event) {
    event.preventDefault();
    resetView();

    const file = fileInput.files?.[0];
    if (!file) {
      statusEl.textContent = "请先选择 PDF 文件。";
      statusEl.className = "status error";
      return;
    }

    statusEl.textContent = "正在上传并解析，请稍候…";
    statusEl.className = "status info";

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("/api/structured/analyze", {
        method: "POST",
        body: formData,
      });
      const payload = await response.json();

      if (!response.ok || !payload.success) {
        throw new Error(payload.error || "解析失败");
      }

      statusEl.textContent = `解析成功，耗时 ${payload.cpu_time_seconds.toFixed(
        3,
      )} 秒。历史次数：${payload.total_analysis_count}`;
      statusEl.className = "status success";

      renderSummary(payload.data);
      renderNldftRows(payload.data.nldft_data || []);
      rawPre.textContent = payload.data.raw_text || "";
      resultCard.hidden = false;
    } catch (error) {
      statusEl.textContent = error.message || "解析失败";
      statusEl.className = "status error";
    }
  }

  form.addEventListener("submit", submitForm);
});

