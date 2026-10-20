# How queues form, persist, and clear

This is a qualitative teaching reference, not measured business data. Small
groups are illustrative examples. Walking distance, animation speed, colors,
and on-screen seconds do not represent real customer speeds or service rates.

## What is being counted

A customer arrives, may wait, starts receiving service, and eventually
finishes. Waiting and receiving service are different states. The whole
system contains both waiting customers and customers currently being helped.
Moving from the waiting line to a desk reduces the waiting count but does
not yet remove anyone from the whole system. Completion followed by departure
does remove a customer. Waiting time ends when service begins; total time
in the system also includes service time. These distinctions follow the
[definitions in MIT's Urban Operations Research text, section 4.3](https://web.mit.edu/urban_or_book/www/book/chapter4/4.3.html).

## Counting change over an interval

For the simplified system here, everyone who arrives stays until service is
completed. Nobody abandons the line or is turned away. The number still in
the system equals the number initially present, plus arrivals, minus completed
departures. Count waiting and service positions together when using this
relationship. If more arrive than depart during an interval, unfinished work
increases. If more depart than arrive, it decreases. Equal arrival and departure
counts leave the total unchanged; they do not erase an existing backlog.
These are finite-interval counting consequences of the
[arrival/departure balance in MIT section 4.4](https://web.mit.edu/urban_or_book/www/book/chapter4/4.4.html).

A simple illustrative example: starting with four unfinished requests,
adding two arrivals and completing one leaves five unfinished requests.
Starting with four, adding one and completing two leaves three. Adding one
and completing one leaves four. These are arithmetic examples, not statistics
about a real service. Waiting counts must be stated separately if some of
those requests move into service during the example.

## Capacity and parallel service

In this illustration, each desk helps one customer at a time. A second desk
can work at the same time as the first if it handles the same requests and
has the resources to do so. It increases available service capacity. Both
desks need actual work and completed service for that capacity to become
departures. Opening a desk can immediately move a waiting person into service;
that person is still unfinished until service ends. Existing unfinished work
only decreases over an interval when completions exceed arrivals. A second
desk alone is therefore not a guarantee that an existing backlog will clear.
Extra capacity can still help by slowing the growth of unfinished work or by
allowing a waiting customer to begin sooner, even during an interval when
arrivals still exceed departures. "Helps" and "clears the backlog" are different
claims; only the latter requires enough excess completions to remove the backlog.
The parallel-server interpretation follows MIT section 4.3 above.

## Timing matters

Arrivals need not be evenly spaced, and requests need not take equal amounts
of work. Several arrivals close together can create a temporary line while
the desks are occupied. A later quiet interval may let the desks catch up.
An average or one snapshot does not describe every instant. This is consistent
with [Columbia Business School's description of variability and temporary
congestion](https://caseworks.business.columbia.edu/caseworks/queueing-management-and-models).

## Scope of the illustration

The examples use a shared first-in-first-out waiting line and one or two
service positions. This is an explicit modeling choice, not a claim that all
real queues use this rule. The same arrival, waiting, processing and completion
states can describe parcels at a packing bench or requests handled by a
computer. Their real processing rules may differ. No particular business,
waiting-time guarantee, percentage, economic result or probability estimate
is implied by these examples.
