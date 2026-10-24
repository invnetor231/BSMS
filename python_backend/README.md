# BSMS SHARPpy API

Este serviço Python calcula índices com a biblioteca SHARPpy a partir dos níveis observados fornecidos pelo frontend. Não cria sondagens nem preenche alturas ausentes.

## Publicação no Render
1. Coloque a pasta `python_backend` na raiz do repositório `BSMS` (ou publique esta pasta como um serviço separado).
2. Crie um serviço Web no Render com runtime Python, diretório raiz `python_backend`, build `pip install -r requirements.txt` e start `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 90`.
3. Defina `ALLOWED_ORIGIN=https://bsms1.netlify.app`.
4. Copie a URL HTTPS gerada pelo Render e cole em `SHARPPY_API` no `index.html` (sem barra final).
5. Publique novamente o site Netlify.

## Teste
Abra a URL raiz do serviço; deve retornar `{"service":"BSMS SHARPpy","status":"ok",...}`. A rota `POST /indices` recebe JSON com `levels`, em que cada nível deve ter `pressure` (hPa), `height` (m), `temperature` (°C), `dewpoint` (°C), e vento opcional (`wind_direction` graus, `wind_speed` m/s).

A instalação do SHARPpy é feita diretamente do repositório oficial. O deploy deve ser validado nos logs do serviço; não é correto considerar a integração operacional até que a API seja publicada e testada com uma sondagem real.
