# Part 1 - Mock databases:

## Fisrt mock database model:

Products - Customers - transactions

The customers are defined by a unique id, first name, last name, gender, age, adress, company name(if representing a company)

Products would be associated to a name, a price, release_date, 

Transactions have an unique id, a product, customer_id, date, cost_of_production, quantity sold

## Second mock database model:

Users - Subscriptions - Payments - Plans

Users have an unique id, first name, last name, gender, age, signup_date

Subscriptions have an id, user id, start date, end date(null while active so date only appears when subscription ends), plans name

Payments have an unique id, a subscription id, an amount, payment method, a status, payment date

Plans have a name, price, billing period

