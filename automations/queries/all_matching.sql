WITH gg_rounds AS (
    SELECT
        gg.round_number as round_num,
        gg.program,
        gg.type AS type,
        gg.chain_name AS chain_name,
        gg.chain_id AS chain_id,
        gg.round_id AS round_id
    FROM
        program_round_labels gg
    WHERE round_number IS NOT NULL
),
 grants_stack_matching as ( 
  SELECT 
     round_num::text,
     project_name as title,
     match_amount_in_usd,
     project_payout_address as recipient_address,
     project_id,
     im.round_id,
     im.chain_id,
     im.timestamp
  FROM indexer_matching im
  LEFT JOIN gg_rounds gg 
    ON gg.chain_id = im.chain_id 
    AND LOWER(gg.round_id) = im.round_id
  )
SELECT 
    encode(
        digest(
             title || match_amount_in_usd::text || recipient_address || 
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
    round_num::text,
    title,
    match_amount_usd as match_amount_in_usd,
    payoutaddress as recipient_address,
    project_id,
    round_id,
    chain_id,
    timestamp
FROM 
    static_matching
