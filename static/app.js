(function () {
  // 상단 롤링: 1위부터 한 칸씩 올라가고, 마우스를 올리면 멈춤
  var wrap = document.getElementById("tickerWrap");
  var ul = document.getElementById("rollList");
  if (wrap && ul) {
    var i = 0, count = ul.children.length - 1;  // 마지막 줄은 1위 복사본
    setInterval(function () {
      if (count < 2 || wrap.matches(":hover")) return;
      i++;
      ul.style.transition = "transform .45s ease";
      ul.style.transform = "translateY(-" + i * 40 + "px)";
      if (i >= count) setTimeout(function () {
        ul.style.transition = "none"; ul.style.transform = "translateY(0)"; i = 0;
      }, 470);
    }, 2500);
    document.getElementById("ticker").addEventListener("click", function () { wrap.classList.toggle("open"); });
    document.addEventListener("click", function (ev) { if (!ev.target.closest("#tickerWrap")) wrap.classList.remove("open"); });
  }

  // 첫 화면은 5분마다 새 순위가 나왔는지 확인하고, 나왔으면 새로고침
  var gen = document.body.getAttribute("data-generated");
  if (gen) setInterval(function () {
    fetch("latest.json?t=" + Date.now()).then(function (r) { return r.json(); }).then(function (j) {
      if (String(j.generatedAt) !== gen) location.reload();
    }).catch(function () {});
  }, 300000);
})();
