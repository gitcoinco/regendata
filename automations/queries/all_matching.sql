WITH gg_rounds AS (
    SELECT
        gg.round_number AS round_num,
        gg.type AS type,
        gg.chain_name AS chain_name,
        gg.chain_id AS chain_id,
        gg.round_name AS round_name,
        gg.round_id AS round_id
    FROM
        experimental_views.all_rounds_20240810172652 gg
),
 grants_stack_matching as ( 
  SELECT 
     round_num,
     project_name as title,
     CASE 
        WHEN im.round_id = '0xa1d52f9b5339792651861329a046dd912761e9a9' THEN match_amount_in_usd/1000000000000 
        ELSE match_amount_in_usd END AS match_amount_in_usd,
     project_payout_address as recipient_address,
     project_id,
     im.round_id,
     im.chain_id,
     im.timestamp
  FROM 
  indexer_matching im
  LEFT JOIN gg_rounds gg 
    ON gg.chain_id = im.chain_id 
    AND LOWER(gg.round_id) = im.round_id
  )
SELECT 
    encode(
        digest(
            round_num::text || title || match_amount_in_usd::text || recipient_address || 
            project_id || round_id || chain_id::text,
            'sha256'
        ),
        'hex'
    ) AS matching_id,
    round_num,
    title,
    match_amount_in_usd,
    recipient_address,
    project_id,
    round_id,
    chain_id,
    timestamp
FROM 
    grants_stack_matching
UNION
SELECT
    encode(
        digest(
            round_num::text || title || match_amount_usd::text || payoutaddress || 
            project_id || round_id || chain_id::text,
            'sha256'
        ),
        'hex'
    ) AS matching_id,
    round_num,
    title,
    match_amount_usd as match_amount_in_usd,
    payoutaddress as recipient_address,
    project_id,
    round_id,
    chain_id,
    '' as timestamp
FROM 
    static_matching
