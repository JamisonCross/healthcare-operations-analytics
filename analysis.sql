-- Every metric describes synthetic, completed or missed appointments only.
-- No-show rate denominator includes both completed visits and no-shows.
SELECT appointment_type, COUNT(*) AS appointments,
       SUM(no_show) AS no_shows, ROUND(100.0 * AVG(no_show), 2) AS no_show_percent,
       ROUND(AVG(wait_minutes), 2) AS average_wait_minutes
FROM appointments GROUP BY appointment_type ORDER BY no_show_percent DESC;

-- Waiting time is recorded only for attended appointments. SQLite AVG ignores NULL.
SELECT provider, COUNT(*) AS appointments, SUM(1-no_show) AS attended,
       ROUND(AVG(wait_minutes), 2) AS average_wait_minutes
FROM appointments GROUP BY provider ORDER BY average_wait_minutes DESC;

SELECT CASE WHEN lead_days >= 21 THEN '21+ days' ELSE 'Under 21 days' END AS booking_window,
       COUNT(*) AS appointments, ROUND(100.0 * AVG(no_show), 2) AS no_show_percent
FROM appointments GROUP BY booking_window;
