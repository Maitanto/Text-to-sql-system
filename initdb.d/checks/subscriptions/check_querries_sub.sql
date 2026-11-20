-- Here we make sure that: - Subscriptions that start before their user’s signup date.
--                         - Payments dated before their subscription’s start, or after its end date.
--                         - Subscriptions with no payments at all.

SELECT U.LOGIN, U.SIGNUP_DATE, S.PLANS_NAME, S.START_DATE FROM USERS U
JOIN SUBSCRIPTIONS S
ON S.USER_LOGIN = U.LOGIN 
WHERE S.START_DATE < U.SIGNUP_DATE

SELECT P.ID, P.SUBSCRIPTION_ID, P.PAYMENT_DATE, S.START_DATE, S.END_DATE FROM PAYMENTS P
JOIN SUBSCRIPTIONS S
ON P.SUBSCRIPTION_ID = S.ID
WHERE P.PAYMENT_DATE < S.START_DATE OR P.PAYMENT_DATE > S.END_DATE

SELECT S.ID FROM SUBSCRIPTIONS S
LEFT JOIN PAYMENTS P
ON S.ID = P.SUBSCRIPTION_ID
WHERE P.ID IS NULL;
