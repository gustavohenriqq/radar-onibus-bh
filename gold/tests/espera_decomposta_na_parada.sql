-- Identidades de cada linha do grao fino:
--   estimada = regular + excesso, e estimada = (media/2)(1 + CV^2).
-- Tambem pega excesso negativo disfarcado: se a conta desse negativo de verdade,
-- o greatest() do modelo zeraria o excesso e a primeira igualdade quebraria.
select *
from {{ ref('fct_headway_parada_faixa') }}
where {{ na_janela() }}
  and (
      abs(espera_estimada_min - espera_regular_min - espera_excesso_min) > 0.000001
   or abs(espera_estimada_min - headway_medio_min / 2 * (1 + cv_headway * cv_headway)) > 0.000001
  )
