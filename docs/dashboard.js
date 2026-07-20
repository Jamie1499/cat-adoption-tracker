async function loadJSON(path) {
  const res = await fetch(path);
  return res.json();
}

async function loadAllCats() {
  const bluecross = await loadJSON("../bluecross_cats.json");
  const battersea = await loadJSON("../battersea_cats.json");
  const catchat = await loadJSON("../catchat_cats.json");

  return [
    ...bluecross.map(c => ({ ...c, source: "Blue Cross" })),
    ...battersea.map(c => ({ ...c, source: "Battersea" })),
    ...catchat.map(c => ({ ...c, source: "CatChat" }))
  ];
}

function renderCats(cats) {
  const container = document.getElementById("cats");
  container.innerHTML = "";

  cats.forEach(cat => {
    const card = document.createElement("div");
    card.className = "cat-card";

    card.innerHTML = `
      <h3>${cat.name}</h3>
      <p><strong>Source:</strong> ${cat.source}</p>
      <p><a href="${cat.url}" target="_blank">View profile</a></p>
    `;

    container.appendChild(card);
  });
}

loadAllCats().then(renderCats);