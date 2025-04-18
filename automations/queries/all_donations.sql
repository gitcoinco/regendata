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
grants_stack_grants AS (
    SELECT 
        gg.round_num,
        (r.round_metadata #>> '{name}')::text AS round_name,
        a.project_id AS project_id, 
        a.status AS status, 
        (a.metadata #>> '{application,project,title}')::text AS project_name,
        a.total_donations_count AS total_donations_count,
        (a.metadata #>> '{application,recipient}')::text AS recipient_address,
        a.id AS application_id,
        a.round_id AS round_id,
        a.chain_id AS chain_id
    FROM applications AS a
    LEFT JOIN 
        gg_rounds gg ON LOWER(gg.round_id) = LOWER(a.round_id)
        AND gg.chain_id = a.chain_id
    LEFT JOIN rounds AS r ON r.id = LOWER(a.round_id) 
        AND r.chain_id = a.chain_id
    -- WHERE a.status = 'APPROVED'
), 
grants_stack_donations AS (
    SELECT 
        gsg.round_num,
        gsg.round_name,
        d.donor_address,
        gsg.project_name,
        gsg.project_id,
        d.amount,
        d.token_address,
        d.amount_in_usd,
        gsg.recipient_address,
        d.chain_id,
        d.timestamp,
        gsg.application_id,
        gsg.round_id
    FROM donations AS d
    JOIN 
        grants_stack_grants gsg ON gsg.application_id = d.application_id
        AND gsg.round_id = d.round_id
        AND gsg.chain_id = d.chain_id
    WHERE d.chain_id != 11155111
)
SELECT 
    encode(
        digest(
            round_num::text || donor_address || amount_in_usd::text || recipient_address || 
            timestamp::text || project_id || round_id || chain_id::text,
            'sha256'
        ),
        'hex'
    ) AS donation_id,
    round_num::text,
    round_name,
    donor_address, 
    amount_in_usd,
    recipient_address,
    timestamp,
    project_name,
    project_id,
    round_id,
    chain_id,
    'GrantsStack' AS source
FROM 
    grants_stack_donations
UNION 
SELECT 
    encode(
        digest(
            round_num::text || donor_address || amount_in_usd::text || recipient_address || 
            timestamp::text || project_id || round_id || chain_id::text,
            'sha256'
        ),
        'hex'
    ) AS donation_id,
    round_num::text,
    round_name,
    donor_address,
    amount_in_usd,
    recipient_address,
    timestamp,
    project_name,
    project_id,
    round_id,
    chain_id,
    source
FROM 
    static_donations
