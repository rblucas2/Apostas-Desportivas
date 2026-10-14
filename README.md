# Scanner de Jogos — apostas desportivas

App web (PWA) que procura, nas principais ligas europeias, jogos de futebol que cumprem os seguintes critérios:

1. **Top 3 vs Últimos 3**: um dos 3 primeiros classificados joga contra um dos 3 últimos da mesma liga.
2. **Série de derrotas**: uma equipa com **mais de 3 derrotas seguidas** (≥ 4, no campeonato) joga contra
   um adversário **melhor classificado**.

Para cada jogo, a app mostra a posição, os pontos, a forma (últimos 5 jogos) e a **cota 1X2 da Betclic**.
Tocar numa cota adiciona-a a um **boletim** que calcula a cota total da combinada e o retorno potencial.
No boletim podes escolher Betclic ou Betano e escrever a cota manualmente. O boletim fica
**sincronizado entre o telemóvel e o PC**.

## Histórico de resultados

O separador **Histórico** mede se os critérios dão lucro. Cada jogo selecionado é registado
em `site/data/historico.json` com a última cota da Betclic antes do jogo. Depois do jogo, o
scanner vai buscar o resultado e liquida uma **aposta simulada de 1 unidade no favorito**
(o melhor classificado): lucro = cota − 1 se ganhar, −1 se empatar ou perder.

- Indicadores: lucro, ROI, taxa de acerto (e a taxa necessária para não perder) e cota média.
- Gráfico do lucro acumulado e tabelas por critério, por intervalo de cota e por liga.
- Um jogo que deixa de cumprir os critérios antes de começar sai do registo. Jogos adiados,
  ou sem resultado 10 dias depois, ficam "anulados" e não contam.
- Jogos sem cota contam para a taxa de acerto, mas não para o lucro nem para o ROI.
- O registo começa no dia em que esta funcionalidade foi ativada. Não há dados retroativos,
  porque a ESPN não guarda classificações passadas e o plano gratuito da The Odds API não tem
  cotas históricas.
- Com poucas apostas, o resultado depende muito da sorte. Antes de tirar conclusões, convém
  juntar algumas centenas de apostas.

## Arquitetura

```
GitHub Actions (a cada 6 h)
  └─ scanner/scan.py  → classificações + resultados + calendário (API pública ESPN)
                      → cotas Betclic (The Odds API, 1×/dia)
                      → site/data/jogos.json  (guardado no repositório)
site/  (PWA estática: index.html, app.js, sw.js…)  → publicada no GitHub Pages
Boletim  ↔  Gist privado do GitHub  (sincronização telemóvel ↔ PC)
```

Os parâmetros (número de equipas no topo e no fundo, derrotas mínimas, dias à frente e lista de ligas)
estão em [`scanner/config.json`](scanner/config.json).

## Configuração (uma vez)

1. **Chave de cotas**: cria uma conta gratuita em <https://the-odds-api.com> (500 créditos/mês).
   No repositório: *Settings → Secrets and variables → Actions → New repository secret*,
   com o nome `ODDS_API_KEY`. Sem esta chave a app funciona, mas não mostra cotas.
2. **Publicação (GitHub Pages)**: *Settings → Pages → Source: GitHub Actions*. Depois, em
   *Settings → Secrets and variables → Actions → Variables*, cria `DEPLOY_PAGES` = `true`.
   - O GitHub Pages num **repositório privado** exige um plano pago (GitHub Pro). Alternativas
     gratuitas: tornar o repositório público, ou ligar a pasta `site/` ao Cloudflare Pages ou
     ao Netlify. Ambos aceitam repositórios privados e voltam a publicar a cada commit de dados.
3. **Primeira execução**: *Actions → Scanner de jogos → Run workflow*.
4. **Instalar no telemóvel**: abre o endereço do site e escolhe "Adicionar ao ecrã principal".
5. **Sincronização**: cria um token *classic* só com a permissão `gist`
   (*GitHub → Settings → Developer settings → Personal access tokens*) e cola-o em
   **Definições** na app, tanto no telemóvel como no PC.

## Executar localmente

```bash
python3 scanner/scan.py                 # sem cotas
ODDS_API_KEY=xxxx python3 scanner/scan.py --ligas por.1,eng.1
python3 -m unittest discover -s scanner/tests
cd site && python3 -m http.server 8000  # abrir http://localhost:8000
```

## Limitações (importante)

- **Cotas**: a Betclic e a Betano não têm API pública, e fazer scraping dos sites viola os termos de
  utilização de ambas. As cotas vêm da The Odds API (casa `betclic_fr`, ou seja, a Betclic França). Podem
  diferir ligeiramente das da Betclic.pt e mudam até ao início do jogo. A **Betano não está coberta**,
  por isso a cota tem de ser introduzida manualmente no boletim. Confirma sempre a cota na casa antes
  de apostar.
- **Créditos**: cada liga consultada gasta 1 crédito. Só são consultadas ligas com jogos selecionados,
  uma vez por dia (06:15 UTC), o que deve caber no plano gratuito.
- **ESPN**: é uma API pública mas não documentada oficialmente. Não aceita intervalos de datas, por isso os resultados vêm do calendário de cada equipa e os próximos jogos são pedidos dia a dia (cerca de 600 pedidos e 1 a 2 minutos por execução). Pode mudar sem aviso. Uma liga
  que falhe aparece como "Erro" em *Estado das ligas analisadas*, sem afetar as outras.
- **Séries de derrotas**: contam só jogos do campeonato (não incluem taças nem competições europeias).
  No início da época a classificação tem pouco valor informativo: vê o número de jogos (J) no cartão.
- **Ligas**: a lista cobre as principais ligas europeias com oferta na Betclic. Para acrescentar uma
  liga, junta uma entrada a `config.json` com o código ESPN e o `sport_key` da The Odds API.

> Os critérios são filtros de seleção, não previsões. Joga com responsabilidade.
