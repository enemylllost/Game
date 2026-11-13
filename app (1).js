<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<meta name="theme-color" content="#09090b"><title>Криминальная империя</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<div id="app">
  <header class="top"><div class="brand"><span class="crown">♛</span><div><b>КРИМИНАЛЬНАЯ ИМПЕРИЯ</b><small>ТВОЙ ГОРОД. ТВОИ ПРАВИЛА.</small></div></div><button class="round" id="refresh">↻</button></header>
  <main>
    <section class="hero">
      <div class="city"></div><div class="hero-shade"></div>
      <div class="profile"><div class="avatar">♛</div><div class="who"><b id="playerName">Игрок</b><span>Уровень <strong id="level">1</strong></span><div class="xp"><i id="xpbar"></i></div><small id="xptext">0 / 40 XP</small></div><div class="wallet"><small>БАЛАНС</small><b id="balance">5 000 ₽</b></div></div>
      <div class="hero-caption"><span>ГОРОД НЕ СПИТ</span><b>Империя начинается с тебя</b></div>
    </section>
    <section class="promo panel"><div class="promo-icon">🏙️</div><div><b>Твоя империя растёт!</b><p>Развивай бизнес, зарабатывай и стань главным в городе.</p></div><span class="chev">›</span></section>
    <section class="stats"><div class="stat panel"><small>ДОСТУПНЫЙ БАЛАНС</small><b id="balance2">5 000 ₽</b></div><div class="stat panel"><small>ДОХОД В ЧАС</small><b class="green" id="income">0 ₽</b></div></section>
    <section class="collect panel"><div><small>НАКОПЛЕННЫЙ ДОХОД</small><b id="pending">0 ₽</b></div><button class="gold-btn" data-action="collect">СОБРАТЬ</button></section>
    <section class="section-head"><h2 id="sectionTitle">Твой бизнес</h2><span class="tag">ИМПЕРИЯ</span></section>
    <section id="homeAssets" class="asset-list"></section>
    <section id="view" class="hidden"></section>
  </main>
  <nav class="bottom">
    <button class="nav active" data-tab="home"><span>⌂</span>Главная</button>
    <button class="nav" data-tab="shop"><span>▣</span>Магазин</button>
    <button class="nav" data-tab="jobs"><span>⚔</span>Криминал</button>
    <button class="nav" data-tab="top"><span>♛</span>Рейтинг</button>
    <button class="nav" data-tab="tasks"><span>☷</span>Задания</button>
  </nav>
  <div id="toast" class="toast"></div>
  <div id="loading" class="loading"><div class="spinner"></div><span>Загрузка империи…</span></div>
</div>
<script src="/static/app.js"></script>
</body></html>