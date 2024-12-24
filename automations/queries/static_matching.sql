WITH alpha_matching AS (
  SELECT am."round_num" AS "round_num",
    am."title" AS "title",
    am."match_amount_dai" AS "match_amount_usd",
    am."sub_round_slug" AS "sub_round_slug",
    addr."address" AS "payoutaddress",
    'unknown' AS "project_id",
    '2023-04-01'::DATE AS "payout_tx_date"
  FROM "public"."AlphaMatching" am
  LEFT JOIN "public"."AlphaRoundGranteeAddresses" addr ON addr."title" = am."title"
),
cgrants AS (
  SELECT cg."grantid" AS "grant_id",
    cg."name" AS "name",
    cg."payoutaddress" AS "payoutaddress"
  FROM "public"."cgrantsGrants" cg
),
cgrants_matching AS (
  SELECT cgm."round_num" AS "round_num",
  CONCAT('Gitcoin Grants ', cgm.round_num) as round_name,
    cg."name" AS "title",
    cgm."sub_round_slug" AS "sub_round_slug",
    cgm."match_amount" AS "match_amount_usd",
    cg."payoutaddress" AS "payoutaddress",
    cg."grant_id" AS "project_id",
    cgm."payout_tx_date" AS "payout_tx_date"
  FROM "experimental_views"."cgrants_matching_timing2_20241016193840" cgm
  LEFT JOIN cgrants cg ON cg."grant_id" = cgm."grant_id"
),
static_matching AS (
  SELECT "round_num",
    "title",
    "match_amount_usd",
    "payoutaddress",
    project_id,
    "sub_round_slug" AS round_id,
    1 AS chain_id,
    "payout_tx_date"::TIMESTAMP AS timestamp
  FROM alpha_matching
  UNION
  SELECT "round_num",
    "title",
    "match_amount_usd",
    "payoutaddress",
    project_id::TEXT,
    "sub_round_slug" AS round_id,
    1 AS chain_id,
    "payout_tx_date"::TIMESTAMP AS timestamp
  FROM cgrants_matching
)
SELECT *
FROM static_matching