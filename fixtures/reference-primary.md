# Reference: what happens after you enter a website address

Simplified facts for a beginner explainer. The script may simplify these
further, but it must not add claims that go beyond them.

- A website address such as www.example.com contains a domain name, which is
  chosen so people can remember it. Computers on the internet find each other
  by numeric IP addresses instead.
- Before contacting the website, the browser needs the server's IP address. It
  asks the Domain Name System (DNS), usually through a DNS resolver run by the
  internet provider or another service. The resolver answers with the IP
  address, and the answer is often stored for a while so later visits are faster.
- The browser then opens a connection to the server at that IP address. When
  the address starts with https, the connection is encrypted so other people on
  the network cannot read what is sent.
- The browser sends an HTTP request that names the page it wants. The request
  and the reply travel across the internet as many small packets, which routers
  pass along toward their destination.
- The web server sends back an HTTP response. For a web page, the main part is
  an HTML document that describes the page's text and structure.
- The browser reads the HTML, requests the other files it refers to, such as
  images, style sheets and scripts, and then draws the page on the screen.
- On a fast connection, the whole process often takes only a second or two.
