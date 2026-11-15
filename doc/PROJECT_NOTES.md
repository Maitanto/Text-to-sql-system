# Part 1 - Mock databases:

## Fisrt mock database model:

Products - Customers - transactions

The customers are defined by a unique id, name, gender, age, adress, company name(if representing a company)

Products would be associated to a name, category, a price, release_date, 

Transactions have an unique id, a product, customer_id, date, the amount payed for the product, cost_of_production, quantity sold

## Second mock database model:

Users - Subscriptions - Payments - Plans

Users have an unique id, name, gender, age, signup_date

Subscriptions have an id, user id, start date, end date(null while active so date only appears when subscription ends), plans name

Payments have an unique id, a subscription id, an amount, payment method, a status, payment date

Plans have a name, price, billing period

