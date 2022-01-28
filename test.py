import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

ax = plt.subplot(111)
ax.plot([x * 100 for x in range(10)], [y * 100 for y in range(10)])
tick = ticker.MultipleLocator(300)
ax.xaxis.set_major_locator(tick)
plt.show()